import { useEffect, useRef, useState } from 'react';
import TabInfoBanner from './TabInfoBanner';

const API_BASE = import.meta.env.VITE_API_URL || '';
const REQUEST_TIMEOUT_MS = 8000;

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
  return <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border whitespace-nowrap ${tones[tone] || tones.neutral}`}>{value}</span>;
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

async function fetchJsonWithTimeout(url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    const text = await res.text();
    let body = {};
    try { body = text ? JSON.parse(text) : {}; } catch { body = { error: text || `HTTP ${res.status}` }; }
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    return body;
  } finally {
    clearTimeout(timer);
  }
}

export default function NextDayWatchlist() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [scanStatus, setScanStatus] = useState(null);
  const [triggering, setTriggering] = useState(false);
  const [triggerMessage, setTriggerMessage] = useState(null);
  const scanInProgressRef = useRef(false);

  const loadScanStatus = async () => {
    try {
      const status = await fetchJsonWithTimeout(`${API_BASE}/api/next-day-watchlist/scan/`);
      scanInProgressRef.current = !!status.scan_in_progress;
      setScanStatus(status);
      return status;
    } catch {
      return null;
    }
  };

  const loadWatchlist = async () => {
    try {
      const d = await fetchJsonWithTimeout(`${API_BASE}/api/next-day-watchlist/`);
      setData(d);
      setError(null);
      return d;
    } catch (e) {
      // Do not destroy a previously displayed list just because one poll
      // timed out while the backend is scanning.
      if (!data) setError(e.name === 'AbortError' ? 'Watchlist request timed out; scan may still be running.' : e.message);
      return null;
    } finally {
      setLoading(false);
    }
  };

  const runScanNow = async () => {
    setTriggering(true);
    setTriggerMessage(null);
    setError(null);
    try {
      const d = await fetchJsonWithTimeout(`${API_BASE}/api/next-day-watchlist/scan/`, { method: 'POST' });
      setTriggerMessage(d.reason || 'Scan started.');
      await loadScanStatus();
      await loadWatchlist();
    } catch (e) {
      setTriggerMessage(`Couldn't start scan: ${e.name === 'AbortError' ? 'backend did not respond within 8 seconds' : e.message}`);
    } finally {
      setTriggering(false);
    }
  };

  useEffect(() => {
    // Never block the entire tab on the first API request. The page,
    // Run Scan button, progress area and polling remain usable immediately.
    loadScanStatus();
    loadWatchlist();
    const interval = setInterval(async () => {
      const status = await loadScanStatus();
      if (status?.scan_in_progress) await loadWatchlist();
      else if (!scanInProgressRef.current) await loadWatchlist();
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      if (!scanInProgressRef.current) loadWatchlist();
    }, 300000);
    return () => clearInterval(interval);
  }, []);

  const watchlist = data?.watchlist || [];
  const actionableCount = watchlist.filter(s => s.score >= 70).length;
  const heavyAccumulationCount = watchlist.filter(s => s.volume_status === 'Heavy Accumulation').length;

  return (
    <div className="space-y-4">
      <TabInfoBanner>
        Full-NSE-universe scan, run manually via the button below -- 100% Fyers-sourced
        (no Screener.in, no third-party data). Trend Status, Volume Status, Sector Strength, and Score are real,
        computed indicators (RSI, distance from 20-day SMA, volume vs. its own 20-day average) combined with
        transparent, documented weights. Stocks under ₹50 or averaging under 1L shares/day are excluded before ranking.
        Every completed scan also records the Top 10 and later fills their actual next-trading-day performance
        into the persistent Excel research ledger: next-day OHLC, close return, maximum intraday gain and drawdown.
      </TabInfoBanner>

      <div className="bg-slate-900/60 border border-slate-800 rounded-xl px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs text-slate-300">
              {scanStatus?.scan_in_progress
                ? (scanStatus.progress?.total > 0
                    ? `🔄 Scanning: ${scanStatus.progress.scanned} / ${scanStatus.progress.total} (${scanStatus.progress.current_symbol?.replace('NSE:', '').replace('-EQ', '') || '…'})`
                    : '🔄 Scan starting — fetching the full symbol list...')
                : scanStatus?.last_result
                  ? `Last run (${scanStatus.last_result.trigger}): ${scanStatus.last_result.universe} scanned, ${scanStatus.last_result.watchlist_len} ranked, finished ${new Date(scanStatus.last_result.finished_at).toLocaleTimeString('en-IN')}`
                  : 'No scan run yet this session.'}
            </p>
            {triggerMessage && <p className="text-[11px] text-slate-500 mt-1">{triggerMessage}</p>}
            {error && <p className="text-[11px] text-amber-400 mt-1">{error}</p>}
          </div>
          <button
            onClick={runScanNow}
            disabled={triggering || scanStatus?.scan_in_progress}
            className="text-xs font-medium px-3 py-2 rounded-lg bg-purple-500/15 text-purple-300 border border-purple-500/25 hover:bg-purple-500/25 transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap shrink-0"
          >
            {scanStatus?.scan_in_progress ? 'Running...' : '🔭 Run Scan Now'}
          </button>
        </div>
        {scanStatus?.scan_in_progress && scanStatus.progress?.total > 0 && (
          <div className="mt-2.5 h-1.5 rounded-full bg-slate-800 overflow-hidden">
            <div className="h-full bg-purple-500 transition-all duration-500" style={{ width: `${Math.min(100, (scanStatus.progress.scanned / scanStatus.progress.total) * 100)}%` }} />
          </div>
        )}
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

      {data?.generated_at && <p className="text-[11px] text-slate-600 text-right">Latest ranking: {new Date(data.generated_at).toLocaleString('en-IN')}</p>}

      {watchlist.length > 0 && (
        <div className="flex items-center gap-2 pt-1">
          <div className="w-1 h-5 bg-purple-500 rounded-full" />
          <h2 className="text-base font-semibold text-white">Tomorrow's Top {watchlist.length} Setups</h2>
        </div>
      )}

      {watchlist.length === 0 ? (
        <div className="py-10 text-center text-slate-500 text-sm max-w-md mx-auto">
          {scanStatus?.scan_in_progress
            ? 'Scan is running — genuine stocks will appear here as ranking checkpoints are published.'
            : (data?.error || 'No scan run yet. Tap "Run Scan Now" above to generate tomorrow\'s watchlist.')}
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
                    <button onClick={() => window.open(`https://www.tradingview.com/chart/?symbol=NSE:${s.symbol.replace('NSE:', '').replace('-EQ', '')}`, '_blank', 'noopener,noreferrer')} className="font-semibold text-sky-400 hover:text-sky-300 hover:underline whitespace-nowrap transition-colors" title={`Open ${s.symbol.replace('NSE:', '').replace('-EQ', '')} chart on TradingView`}>
                      {s.symbol.replace('NSE:', '').replace('-EQ', '')}
                    </button>
                  </td>
                  <td className="px-3 py-2.5 text-slate-400 whitespace-nowrap">{s.sector}</td>
                  <td className="px-3 py-2.5 text-right text-white whitespace-nowrap">₹{fmt(s.eod_price)}</td>
                  <td className="px-3 py-2.5 text-right">
                    <span className={`font-bold tabular-nums ${s.score >= 70 ? 'text-emerald-400' : s.score >= 40 ? 'text-amber-400' : 'text-slate-500'}`}>{s.score}</span>
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
