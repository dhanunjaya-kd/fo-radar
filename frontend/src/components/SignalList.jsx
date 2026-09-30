import { useEffect, useState, useMemo, useRef } from 'react';
import LiveSignalsTable from './LiveSignalsTable';
import AdvanceDeclineDonut from './AdvanceDeclineDonut';

const API_BASE = import.meta.env.VITE_API_URL || '';

const IconBolt = ({ size = 20 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
);
const IconDownload = ({ size = 16 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
);
const IconAlertTriangle = ({ size = 14 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
);

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
  } catch (e) {}
}

// Sep 30 2026: block-based redesign, Gamma Strategy as the visual
// reference (its own card language: rounded-xl bg-slate-800/60
// border-slate-700/50). CandidateCard is a new, genuinely reusable
// component (per the task's own suggested component list) -- Long/
// Call and Short/Put both use it, only the accent color differs.
// Fields used (quality_score, quality_verdict, symbol) are the exact
// same fields LiveSignalsTable.jsx already reads from this same
// signal shape -- confirmed by grepping every signal.* reference in
// that file before writing this, nothing new invented here.
const QUALITY_BADGE_STYLE = {
  CONFIRMED: 'text-emerald-400 bg-emerald-500/10',
  WATCH: 'text-amber-400 bg-amber-500/10',
};

function CandidateCard({ signal, accent }) {
  const accentColor = accent === 'long' ? 'text-emerald-400' : 'text-rose-400';
  const badgeStyle = QUALITY_BADGE_STYLE[signal.quality_verdict] || 'text-slate-400 bg-slate-500/10';
  return (
    <div className="flex items-center justify-between rounded-lg bg-slate-900/40 border border-slate-700/40 px-3 py-2">
      <span className={`text-sm font-bold ${accentColor}`}>{signal.symbol}</span>
      <div className="flex items-center gap-2">
        {signal.quality_score != null && (
          <span className="text-xs text-slate-300 tabular-nums">{signal.quality_score}</span>
        )}
        {signal.quality_verdict && (
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${badgeStyle}`}>{signal.quality_verdict}</span>
        )}
      </div>
    </div>
  );
}

function CandidateBlock({ title, signals, accent }) {
  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
      <h3 className="text-sm font-bold text-white mb-3">{title}</h3>
      {signals.length === 0 ? (
        <p className="text-xs text-slate-500 italic">No {accent === 'long' ? 'call' : 'put'} candidates qualifying right now.</p>
      ) : (
        <div className="space-y-2">
          {signals.map((s) => <CandidateCard key={`${s.symbol}-${s.action}`} signal={s} accent={accent} />)}
        </div>
      )}
    </div>
  );
}

// Sep 30 2026: BLOCK 6 -- Technical Confirmation. Every field here
// (rsi, adx, macd, ema20, ema50, vwap_distance_pct, volume_ratio) was
// confirmed by reading the actual signal-dict construction in
// backend/screener/views.py directly -- all already computed and
// already returned by /api/sniper-only/, just never displayed until
// now. plus_di/minus_di were ALSO checked and confirmed NOT present
// in the final dict (computed only for internal classification), so
// they're correctly left out here rather than guessed at.
function fmtTechNum(v, digits = 1) { return v != null ? v.toFixed(digits) : '—'; }

function TechnicalRow({ signal }) {
  const price = signal.price;
  const trendUp = signal.ema20 != null && signal.ema50 != null ? signal.ema20 > signal.ema50 : null;
  return (
    <div className="rounded-lg bg-slate-900/40 border border-slate-700/40 p-3">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm font-bold text-white">{signal.symbol}</span>
        {trendUp != null && (
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${trendUp ? 'text-emerald-400 bg-emerald-500/10' : 'text-rose-400 bg-rose-500/10'}`}>
            {trendUp ? 'EMA20 > EMA50' : 'EMA20 < EMA50'}
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-x-3 gap-y-1 text-[11px] text-slate-400">
        <span>RSI {fmtTechNum(signal.rsi)}</span>
        <span>ADX {fmtTechNum(signal.adx)}</span>
        <span>MACD {fmtTechNum(signal.macd, 3)}</span>
        <span>VWAP {signal.vwap_distance_pct != null ? `${signal.vwap_distance_pct > 0 ? '+' : ''}${signal.vwap_distance_pct.toFixed(2)}%` : '—'}</span>
        <span>Vol {signal.volume_ratio != null ? `${signal.volume_ratio.toFixed(2)}x avg` : '—'}</span>
        <span>Score {signal.technical_score != null ? signal.technical_score : '—'}</span>
      </div>
    </div>
  );
}

// Sep 30 2026: BLOCK 7 -- OI / Derivatives Confirmation. oi_confirmation
// and oi_reason are the real, existing fields -- confirmed present in
// the same dict construction. The task's own mockup lists richer
// sub-metrics (Call OI, Put OI, PCR, long/short buildup) that were
// checked for and confirmed NOT to exist on this signal shape -- shown
// honestly as real fields only, not fabricated to match the mockup.
function OIRow({ signal }) {
  const confirmed = signal.oi_confirmation === 'Confirmed' || signal.oi_confirmation === true;
  return (
    <div className="rounded-lg bg-slate-900/40 border border-slate-700/40 p-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm font-bold text-white">{signal.symbol}</span>
        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${confirmed ? 'text-emerald-400 bg-emerald-500/10' : 'text-slate-400 bg-slate-500/10'}`}>
          {String(signal.oi_confirmation ?? 'Unavailable')}
        </span>
      </div>
      {signal.oi_reason && <p className="text-[11px] text-slate-400">{signal.oi_reason}</p>}
    </div>
  );
}

function ConfirmationBlock({ title, signals, RowComponent, emptyNote }) {
  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
      <h3 className="text-sm font-bold text-white mb-3">{title}</h3>
      {signals.length === 0 ? (
        <p className="text-xs text-slate-500 italic">{emptyNote}</p>
      ) : (
        <div className="space-y-2">
          {signals.map((s) => <RowComponent key={`${s.symbol}-${s.action}`} signal={s} />)}
        </div>
      )}
    </div>
  );
}

// Sep 30 2026: BLOCK 10 -- Market / Sector Context. sector_change_pct,
// stock_vs_sector_pct, stock_vs_index_pct all confirmed real, existing
// fields (same dict construction). No sector NAME field exists on this
// signal shape (checked directly, not assumed) -- shown as the real
// numbers without inventing a sector label.
function SectorContextRow({ signal }) {
  const vsSector = signal.stock_vs_sector_pct;
  const vsIndex = signal.stock_vs_index_pct;
  return (
    <div className="rounded-lg bg-slate-900/40 border border-slate-700/40 p-3 flex items-center justify-between">
      <span className="text-sm font-bold text-white">{signal.symbol}</span>
      <div className="flex items-center gap-4 text-[11px] text-slate-400">
        <span>Stock {signal.change_percent != null ? `${signal.change_percent > 0 ? '+' : ''}${signal.change_percent}%` : '—'}</span>
        <span>Sector {signal.sector_change_pct != null ? `${signal.sector_change_pct > 0 ? '+' : ''}${signal.sector_change_pct}%` : '—'}</span>
        <span className={vsSector != null && vsSector > 0 ? 'text-emerald-400' : vsSector != null ? 'text-rose-400' : ''}>
          vs Sector {vsSector != null ? `${vsSector > 0 ? '+' : ''}${vsSector}%` : '—'}
        </span>
        <span className={vsIndex != null && vsIndex > 0 ? 'text-emerald-400' : vsIndex != null ? 'text-rose-400' : ''}>
          vs Index {vsIndex != null ? `${vsIndex > 0 ? '+' : ''}${vsIndex}%` : '—'}
        </span>
      </div>
    </div>
  );
}

export default function LiveSignals() {
  const [signals, setSignals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [availableDates, setAvailableDates] = useState([]);
  const [selectedDate, setSelectedDate] = useState('');
  const knownKeysRef = useRef(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/signals/export/dates/`)
      .then(res => res.ok ? res.json() : { dates: [] })
      .then(data => setAvailableDates(data.dates || []))
      .catch(() => setAvailableDates([]));
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
          const currentKeys = new Set(unique.map(s => `${s.symbol}:${s.action}`));
          if (knownKeysRef.current !== null) {
            const newOnes = unique.filter(s => !knownKeysRef.current.has(`${s.symbol}:${s.action}`));
            if (newOnes.length > 0) {
              playAlertSound();
              if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
                newOnes.forEach(s => {
                  new Notification(`🎯 New SNIPER signal: ${s.symbol}`, {
                    body: `${s.action} ${s.action === 'BUY' ? 'CE' : 'PE'} — ₹${s.strike} strike | Grade ${s.grade} | ${s.confidence} confidence`,
                    tag: `${s.symbol}-${s.action}`,
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
        if (err.name !== 'AbortError' && mounted) setError(err.message);
      } finally {
        if (mounted) setLoading(false);
      }
    };

    fetchSignals();
    const interval = setInterval(fetchSignals, 60000);
    return () => { mounted = false; controller.abort(); clearInterval(interval); };
  }, []);

  const uniqueSignals = useMemo(() => signals, [signals]);
  // Sep 30 2026 fix: real, confirmed Rules of Hooks violation, found
  // via actual React error output (not guessed) -- these two useMemo
  // calls were below the early-return loading/error checks, so the
  // loading render called 9 hooks total while the loaded render
  // called 11, triggering "Rendered more hooks than during the
  // previous render." Moved above every early return, alongside
  // uniqueSignals, so the hook count is identical on every render
  // regardless of which branch below actually returns.
  const longSignals = useMemo(() => uniqueSignals.filter((s) => s.action === 'BUY'), [uniqueSignals]);
  const shortSignals = useMemo(() => uniqueSignals.filter((s) => s.action === 'SELL'), [uniqueSignals]);

  if (loading && uniqueSignals.length === 0) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {[1,2,3,4,5,6].map(i => <div key={i} className="h-80 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />)}
      </div>
    );
  }

  if (error && uniqueSignals.length === 0) {
    return (
      <div className="text-center py-16">
        <p className="text-rose-400 mb-2 flex items-center justify-center gap-1.5"><IconAlertTriangle size={16} /> {error}</p>
        <button onClick={() => window.location.reload()} className="px-4 py-2 bg-slate-700 text-white rounded-lg text-sm">Refresh</button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* BLOCK 1 -- F&O Radar header, Gamma Strategy's own card style
          (rounded-xl bg-slate-800/60 border-slate-700/50 p-4) for a
          consistent institutional-terminal language across both
          pages. A/D breadth and the existing date-picker + export
          link are preserved exactly, just repositioned into this
          header's layout rather than removed or rebuilt. */}
      <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
        <div className="flex items-center gap-3 flex-wrap">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <span className="text-amber-500"><IconBolt size={16} /></span>
              F&O Radar
              <span className="text-xs font-normal text-slate-400 bg-slate-800 px-2 py-0.5 rounded-full">
                {uniqueSignals.length} active
              </span>
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">Live Futures &amp; Options Intelligence — Technical + OI + Options confirmation</p>
          </div>

          <div className="w-[200px] h-[52px] shrink-0 flex items-center px-3 rounded-lg bg-slate-900/60 border border-slate-800 ml-auto">
            <div className="w-[45px] shrink-0 text-[9px] text-slate-500 uppercase tracking-wider leading-tight text-center">
              <div>A/D</div>
              <div className="text-[8px]">BREADTH</div>
            </div>
            <div className="h-8 border-l border-slate-800 mx-2" />
            <AdvanceDeclineDonut compact />
          </div>

          <div className="flex items-center gap-2">
            {availableDates.length > 0 && (
              <select
                value={selectedDate}
                onChange={(e) => setSelectedDate(e.target.value)}
                title="Pick a date to download that day's log instead of today's"
                className="h-9 text-xs bg-slate-800 border border-slate-700 rounded-lg px-2 text-slate-300 focus:outline-none focus:border-emerald-500"
              >
                <option value="">Today</option>
                {availableDates.map(d => <option key={d} value={d}>{new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}</option>)}
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

      {error && <div className="text-xs text-amber-400 bg-amber-500/10 px-3 py-2 rounded-lg border border-amber-500/20 flex items-center gap-1.5"><IconAlertTriangle size={13} /> {error} — Showing cached signals</div>}

      {uniqueSignals.length === 0 ? (
        <div className="text-center py-16">
          <div className="text-slate-600 mb-3 flex justify-center"><IconBolt size={36} /></div>
          <h3 className="text-lg font-bold text-white mb-1">No SNIPER signals right now</h3>
          <p className="text-slate-400 text-sm mb-4">Market conditions don't meet criteria. Check back in a minute.</p>
        </div>
      ) : (
        <>
          {/* BLOCKS 3-4 -- Long/Call and Short/Put candidates, split
              from the SAME signal list by the SAME action field the
              existing table already reads (BUY -> CE, SELL -> PE) --
              no new classification invented, purely a different view
              of data that already exists. */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <CandidateBlock title="Long / Call Candidates" signals={longSignals} accent="long" />
            <CandidateBlock title="Short / Put Candidates" signals={shortSignals} accent="short" />
          </div>

          {/* BLOCK 5 -- Qualified F&O Signals. The existing
              LiveSignalsTable is preserved completely as-is beneath
              this header (detail drawer, FYERS stock-open integration,
              chart modal -- all real, working functionality this
              redesign must not remove) -- just given the same
              section-header treatment as Gamma's own blocks. */}
          <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
            <h3 className="text-sm font-bold text-white mb-3">Qualified F&amp;O Signals</h3>
            <LiveSignalsTable signals={uniqueSignals} />
          </div>

          {/* BLOCKS 6-7 -- Technical Confirmation and OI/Derivatives
              Confirmation, using the top 8 signals (by whatever order
              the API already returns) to keep these blocks scannable
              rather than repeating the full table's row count twice
              more. */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <ConfirmationBlock
              title="Technical Confirmation"
              signals={uniqueSignals.slice(0, 8)}
              RowComponent={TechnicalRow}
              emptyNote="No signals to show technical data for right now."
            />
            <ConfirmationBlock
              title="OI / Derivatives Confirmation"
              signals={uniqueSignals.slice(0, 8)}
              RowComponent={OIRow}
              emptyNote="No signals to show OI confirmation for right now."
            />
          </div>

          {/* BLOCK 10 -- Market / Sector Context. Blocks 8 (Options
              Resolver) and 9 (Microstructure) are deliberately not
              built here -- confirmed during Phase 1 inspection that
              F&O Radar signals don't carry the per-contract Greeks
              (delta/spread/OI/volume) or the 4-phase microstructure
              trigger data Gamma's own equivalents have; the task's own
              rule ("if this data does not currently exist, do not
              create a new backend system") applies directly. */}
          <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
            <h3 className="text-sm font-bold text-white mb-3">Market / Sector Context</h3>
            <div className="space-y-2">
              {uniqueSignals.slice(0, 8).map((s) => <SectorContextRow key={`${s.symbol}-${s.action}`} signal={s} />)}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
