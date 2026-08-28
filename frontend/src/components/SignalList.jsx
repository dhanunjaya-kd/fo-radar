import { useEffect, useState, useMemo, useRef } from 'react';
import LiveSignalsTable from './LiveSignalsTable';

// Relative on purpose -- Vite's dev-server proxy (vite.config.js) forwards
// /api/* to the Django backend on this same machine, so this works
// identically whether the page loaded from localhost, your home wifi IP,
// or a Tailscale IP. Set VITE_API_URL to override for a real deployment
// (e.g. a separately-hosted backend), where there's no dev-server proxy.
const API_BASE = import.meta.env.VITE_API_URL || '';

// Icon set matches the stroke-based style already used in Analytics.jsx
// (OI Analytics tab) -- currentColor-driven SVGs instead of emoji, so
// theming (amber/emerald tone classes) actually applies to them.
const IconBolt = ({ size = 20 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
);
const IconDownload = ({ size = 16 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
);
const IconAlertTriangle = ({ size = 14 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
);

// Two-tone "ping" via Web Audio API -- no external sound file to ship.
function playAlertSound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const playTone = (freq, startTime, duration) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = freq;
      osc.type = 'sine';
      gain.gain.setValueAtTime(0.15, startTime);
      gain.gain.exponentialRampToValueAtTime(0.001, startTime + duration);
      osc.start(startTime);
      osc.stop(startTime + duration);
    };
    const now = ctx.currentTime;
    playTone(880, now, 0.15);
    playTone(1100, now + 0.15, 0.2);
  } catch (e) {
    // Web Audio blocked/unavailable -- browser notification (if enabled) still fires
  }
}

export default function LiveSignals() {
  const [signals, setSignals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // Past-day export picker -- '' means "today" (the original single
  // download button's behavior, unchanged). Populated once from
  // /api/signals/export/dates/, which lists every date that actually
  // has a log, newest first.
  const [availableDates, setAvailableDates] = useState([]);
  const [selectedDate, setSelectedDate] = useState('');
  // null = first load -- don't alert for signals that were already active
  // when the page opened, only for ones that appear AFTER that.
  const knownKeysRef = useRef(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/signals/export/dates/`)
      .then(res => res.ok ? res.json() : { dates: [] })
      .then(data => setAvailableDates(data.dates || []))
      .catch(() => setAvailableDates([])); // date picker just won't show -- not worth surfacing an error for
  }, []);

  useEffect(() => {
    let mounted = true;
    const controller = new AbortController();

    const fetchSignals = async () => {
      try {
        if (mounted) setLoading(true);
        const res = await fetch(`${API_BASE}/api/sniper-only/`, {
          signal: controller.signal,
          headers: { 'Accept': 'application/json' }
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (mounted) {
          const seen = new Set();
          const unique = (data.signals || []).filter(s => {
            if (seen.has(s.symbol)) return false;
            seen.add(s.symbol);
            return true;
          });

          // New-signal detection -- so you can act quickly instead of
          // having to keep the tab open and watch it.
          const currentKeys = new Set(unique.map(s => `${s.symbol}:${s.action}`));
          if (knownKeysRef.current !== null) {
            const newOnes = unique.filter(s => !knownKeysRef.current.has(`${s.symbol}:${s.action}`));
            if (newOnes.length > 0) {
              playAlertSound();
              if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
                newOnes.forEach(s => {
                  new Notification(`🎯 New SNIPER signal: ${s.symbol}`, {
                    body: `${s.action} ${s.action === 'BUY' ? 'CE' : 'PE'} — ₹${s.strike} strike | Grade ${s.grade} | ${s.confidence} confidence`,
                    tag: `${s.symbol}-${s.action}`, // replaces rather than stacks if it fires again
                  });
                });
              }
            }
          }
          knownKeysRef.current = currentKeys;

          setSignals(unique);
          setError(null);
        }
      } catch (err) {
        if (err.name !== 'AbortError' && mounted) {
          setError(err.message);
        }
      } finally {
        if (mounted) setLoading(false);
      }
    };

    fetchSignals();
    const interval = setInterval(fetchSignals, 60000);
    return () => { mounted = false; controller.abort(); clearInterval(interval); };
  }, []);

  // Memoize to prevent re-renders causing duplicates
  const uniqueSignals = useMemo(() => signals, [signals]);

  if (loading && uniqueSignals.length === 0) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {[1,2,3,4,5,6].map(i => (
          <div key={i} className="h-80 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />
        ))}
      </div>
    );
  }

  if (error && uniqueSignals.length === 0) {
    return (
      <div className="text-center py-16">
        <p className="text-rose-400 mb-2 flex items-center justify-center gap-1.5"><IconAlertTriangle size={16} /> {error}</p>
        <button onClick={() => window.location.reload()} className="px-4 py-2 bg-slate-700 text-white rounded-lg text-sm">
          Refresh
        </button>
      </div>
    );
  }

  if (uniqueSignals.length === 0) {
    return (
      <div className="text-center py-16">
        <div className="text-slate-600 mb-3 flex justify-center"><IconBolt size={36} /></div>
        <h3 className="text-lg font-bold text-white mb-1">No SNIPER signals right now</h3>
        <p className="text-slate-400 text-sm mb-4">Market conditions don't meet criteria. Check back in a minute.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <span className="text-amber-500"><IconBolt size={18} /></span>
            SNIPER Signals
            <span className="text-xs font-normal text-slate-400 bg-slate-800 px-2 py-0.5 rounded-full">
              {uniqueSignals.length} active
            </span>
          </h2>
          <div className="flex items-center gap-2">
            {availableDates.length > 0 && (
              <select
                value={selectedDate}
                onChange={(e) => setSelectedDate(e.target.value)}
                title="Pick a date to download that day's log instead of today's"
                className="h-9 text-xs bg-slate-800 border border-slate-700 rounded-lg px-2 text-slate-300 focus:outline-none focus:border-emerald-500"
              >
                <option value="">Today</option>
                {availableDates.map(d => (
                  <option key={d} value={d}>
                    {new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
                  </option>
                ))}
              </select>
            )}
            <a
              href={selectedDate ? `${API_BASE}/api/signals/export/${selectedDate}/` : `${API_BASE}/api/signals/export/`}
              title={selectedDate ? `Download ${selectedDate}'s log (Excel)` : "Download today's log (Excel)"}
              aria-label={selectedDate ? `Download ${selectedDate}'s log (Excel)` : "Download today's log (Excel)"}
              className="w-9 h-9 shrink-0 flex items-center justify-center rounded-lg text-emerald-400 bg-emerald-500/10 border border-emerald-500/25 hover:bg-emerald-500/20 transition-colors"
              download
            >
              <IconDownload size={16} />
            </a>
          </div>
        </div>
      </div>

      {error && (
        <div className="text-xs text-amber-400 bg-amber-500/10 px-3 py-2 rounded-lg border border-amber-500/20 flex items-center gap-1.5">
          <IconAlertTriangle size={13} /> {error} — Showing cached signals
        </div>
      )}

      <LiveSignalsTable signals={uniqueSignals} />
    </div>
  );
}
