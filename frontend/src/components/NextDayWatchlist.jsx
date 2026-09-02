import { useEffect, useState } from 'react';
import TabInfoBanner from './TabInfoBanner';

// Relative on purpose -- see the same note in SignalList.jsx / IndexTracker.jsx.
const API_BASE = import.meta.env.VITE_API_URL || '';

function fmt(n, digits = 2) {
  if (n == null || isNaN(n)) return '—';
  return Number(n).toLocaleString('en-IN', { maximumFractionDigits: digits });
}

function StatusBadge({ value, tone }) {
  if (!value) return <span className="text-slate-600">—</span>;
  const tones = {
    strong: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
    moderate: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/25',
    weak: 'bg-slate-700/40 text-slate-400 border-slate-600/40',
    heavy: 'bg-purple-500/15 text-purple-400 border-purple-500/25',
    leading: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
    lagging: 'bg-rose-500/15 text-rose-400 border-rose-500/25',
    neutral: 'bg-slate-700/40 text-slate-400 border-slate-600/40',
  };
  return (
    <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border whitespace-nowrap ${tones[tone] || tones.neutral}`}>
      {value}
    </span>
  );
}

function trendTone(status) {
  if (status === 'Strong') return 'strong';
  if (status === 'Moderate') return 'moderate';
  if (status === 'Weak') return 'weak';
  return 'neutral';
}

function volumeTone(status) {
  if (status && status.includes('Heavy')) return 'heavy';
  return 'neutral';
}

function sectorTone(status) {
  if (status === 'Leading') return 'leading';
  if (status === 'Lagging') return 'lagging';
  return 'neutral';
}

export default function NextDayWatchlist() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // Sep 2 2026: manual "run it now" trigger -- the automatic post-close
  // scan only fires once a day and depends on the server being up when
  // that window arrives; this lets a scan happen on demand instead.
  const [scanStatus, setScanStatus] = useState(null); // {scan_in_progress, last_result}
  const [triggering, setTriggering] = useState(false);
  const [triggerMessage, setTriggerMessage] = useState(null);

  const loadScanStatus = () => {
    fetch(`${API_BASE}/api/next-day-watchlist/scan/`)
      .then(r => r.json())
      .then(setScanStatus)
      .catch(() => {});
  };

  const runScanNow = async () => {
    setTriggering(true);
    setTriggerMessage(null);
    try {
      const res = await fetch(`${API_BASE}/api/next-day-watchlist/scan/`, { method: 'POST' });
      const d = await res.json();
      setTriggerMessage(d.reason);
      loadScanStatus();
    } catch (e) {
      setTriggerMessage(`Couldn't start scan: ${e.message}`);
    } finally {
      setTriggering(false);
    }
  };

  useEffect(() => {
    loadScanStatus();
    // Poll status a bit faster while a scan might be running (this tab
    // is exactly where someone watches it finish), separate from the
    // main 5-min watchlist-data poll below.
    const interval = setInterval(loadScanStatus, 20000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch(`${API_BASE}/api/next-day-watchlist/`)
        .then(r => r.json())
        .then(d => {
          if (cancelled) return;
          setData(d);
          setError(d.error && d.watchlist?.length === 0 && d.universe_scanned === 0 ? null : null);
        })
        .catch(e => { if (!cancelled) setError(e.message); })
        .finally(() => { if (!cancelled) setLoading(false); });
    };
    load();
    // 5 min -- this only changes once a day (the automatic post-close
    // scan), no need to poll faster.
    const interval = setInterval(load, 300000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  if (loading) {
    return <div className="p-10 text-center text-slate-500 text-sm">Loading Next Day Watchlist...</div>;
  }
  if (error) {
    return <div className="p-10 text-center text-slate-500 text-sm">Couldn't load watchlist: {error}</div>;
  }

  const watchlist = data?.watchlist || [];
  const actionableCount = watchlist.filter(s => s.score >= 70).length;
  const heavyAccumulationCount = watchlist.filter(s => s.volume_status === 'Heavy Accumulation').length;

  return (
    <div className="space-y-4">
      <TabInfoBanner>
        Full-NSE-universe scan, built automatically every weekday shortly after market close -- 100% Fyers-sourced
        (no Screener.in, no third-party data). Trend Status, Volume Status, Sector Strength, and Score are real,
        computed indicators (RSI, distance from 20-day SMA, volume vs. its own 20-day average) combined with
        transparent, documented weights -- not an opaque single number. Sector Strength only computes for stocks
        with a known sector; the rest show Unknown honestly rather than a guess.
      </TabInfoBanner>

      <div className="flex items-center justify-between bg-slate-900/60 border border-slate-800 rounded-xl px-4 py-3 gap-3">
        <div className="min-w-0">
          <p className="text-xs text-slate-300">
            {scanStatus?.scan_in_progress
              ? '🔄 Scan in progress — this typically takes several minutes for the full NSE universe.'
              : scanStatus?.last_result
                ? `Last run (${scanStatus.last_result.trigger}): ${scanStatus.last_result.universe} scanned, ${scanStatus.last_result.watchlist_len} ranked, finished ${new Date(scanStatus.last_result.finished_at).toLocaleTimeString('en-IN')}`
                : 'No scan run yet this session.'}
          </p>
          {triggerMessage && <p className="text-[11px] text-slate-500 mt-1">{triggerMessage}</p>}
        </div>
        <button
          onClick={runScanNow}
          disabled={triggering || scanStatus?.scan_in_progress}
          className="text-xs font-medium px-3 py-2 rounded-lg bg-purple-500/15 text-purple-300 border border-purple-500/25 hover:bg-purple-500/25 transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap shrink-0"
        >
          {scanStatus?.scan_in_progress ? 'Running...' : '🔭 Run Scan Now'}
        </button>
      </div>

      {data && (
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 text-center">
            <p className="text-[10px] text-slate-500 uppercase tracking-wide">Universe Scanned</p>
            <p className="text-2xl font-bold text-cyan-400 mt-1">{data.universe_scanned}</p>
            <p className="text-[10px] text-slate-600">Stocks</p>
          </div>
          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 text-center">
            <p className="text-[10px] text-slate-500 uppercase tracking-wide">Score ≥ 70</p>
            <p className="text-2xl font-bold text-white mt-1">{actionableCount}</p>
            <p className="text-[10px] text-slate-600">of {watchlist.length} listed</p>
          </div>
          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 text-center">
            <p className="text-[10px] text-slate-500 uppercase tracking-wide">Heavy Accumulation</p>
            <p className="text-2xl font-bold text-purple-400 mt-1">{heavyAccumulationCount}</p>
          </div>
        </div>
      )}

      {data?.generated_at && (
        <p className="text-[11px] text-slate-600 text-right">
          Scan completed: {new Date(data.generated_at).toLocaleString('en-IN')}
        </p>
      )}

      {watchlist.length === 0 ? (
        <div className="py-10 text-center text-slate-500 text-sm max-w-md mx-auto">
          {data?.error || 'No scan has completed yet. The automatic scan runs weekdays shortly after market close.'}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-xs sm:text-sm">
            <thead>
              <tr className="bg-slate-900/60 text-slate-500 text-[11px] uppercase tracking-wide">
                <th className="text-left px-3 py-2.5 font-medium">Rank</th>
                <th className="text-left px-3 py-2.5 font-medium">Symbol</th>
                <th className="text-left px-3 py-2.5 font-medium">Sector</th>
                <th className="text-right px-3 py-2.5 font-medium">EOD Price</th>
                <th className="text-right px-3 py-2.5 font-medium">Score</th>
                <th className="text-left px-3 py-2.5 font-medium">Trend Status</th>
                <th className="text-left px-3 py-2.5 font-medium">Volume Status</th>
                <th className="text-left px-3 py-2.5 font-medium">Sector Strength</th>
              </tr>
            </thead>
            <tbody>
              {watchlist.map((s, i) => (
                <tr key={s.symbol} className={`border-t border-slate-800/60 hover:bg-slate-900/40 transition-colors ${i === 0 ? 'bg-slate-900/30' : ''}`}>
                  <td className="px-3 py-2.5 text-slate-400">#{s.rank}</td>
                  <td className="px-3 py-2.5">
                    <span className="font-semibold text-sky-400 whitespace-nowrap">
                      {s.symbol.replace('NSE:', '').replace('-EQ', '')}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-slate-400 whitespace-nowrap">{s.sector}</td>
                  <td className="px-3 py-2.5 text-right text-white whitespace-nowrap">₹{fmt(s.eod_price)}</td>
                  <td className="px-3 py-2.5 text-right">
                    <span className={`font-bold tabular-nums ${s.score >= 70 ? 'text-emerald-400' : s.score >= 40 ? 'text-amber-400' : 'text-slate-500'}`}>
                      {s.score}
                    </span>
                    <span className="text-slate-600">/100</span>
                  </td>
                  <td className="px-3 py-2.5"><StatusBadge value={s.trend_status} tone={trendTone(s.trend_status)} /></td>
                  <td className="px-3 py-2.5"><StatusBadge value={s.volume_status} tone={volumeTone(s.volume_status)} /></td>
                  <td className="px-3 py-2.5"><StatusBadge value={s.sector_strength} tone={sectorTone(s.sector_strength)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
