import { useEffect, useState } from 'react';
import TabInfoBanner from './TabInfoBanner';

// Relative on purpose -- same note as SignalList.jsx/MarketBanner.jsx.
const API_BASE = import.meta.env.VITE_API_URL || '';

const IconPlay = ({ size = 14 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
);
const IconDownload = ({ size = 14 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
);
const IconAlertTriangle = ({ size = 13 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
);
const IconClock = ({ size = 13 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
);
const IconCalendar = ({ size = 13, className = '' }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
);

// Aug 27 2026: pure SVG, no charting library dependency -- avoids any
// risk of the app breaking on a missing npm package (same lesson as
// today's reportlab issue, just for the frontend side). viewBox +
// preserveAspectRatio="none" lets this scale to fill its container
// width responsively while the internal coordinate math stays fixed
// and simple. Coordinate transform verified against edge cases
// (flat curve, single point, declining curve) before being wired in
// here -- see test_equity_svg.js.
function EquityCurveChart({ points, width = 280, height = 100 }) {
  if (!points || points.length < 2) {
    return (
      <div className="h-[100px] flex items-center justify-center text-[10px] text-slate-600">
        Not enough trades yet for a curve
      </div>
    );
  }

  const padding = 4;
  const equities = points.map(p => p.equity);
  const minEq = Math.min(...equities);
  const maxEq = Math.max(...equities);
  const range = maxEq - minEq || 1;
  const usableH = height - padding * 2;
  const stepX = width / (points.length - 1);

  const coords = points.map((p, i) => {
    const x = i * stepX;
    const y = padding + usableH - ((p.equity - minEq) / range) * usableH;
    return [x, y];
  });

  const linePath = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  const areaPath = `${linePath} L ${coords[coords.length - 1][0].toFixed(1)} ${height} L 0 ${height} Z`;

  const isUp = points[points.length - 1].cumulative_pnl >= 0;
  const strokeColor = isUp ? '#34d399' : '#fb7185'; // emerald-400 / rose-400
  const fillId = `eq-fill-${isUp ? 'up' : 'down'}-${Math.round(minEq)}`; // varies per-instance so multiple charts on one page don't share a gradient id

  const firstDate = new Date(points[0].date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  const lastDate = new Date(points[points.length - 1].date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });

  return (
    <div>
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="overflow-visible">
        <defs>
          <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={strokeColor} stopOpacity="0.25" />
            <stop offset="100%" stopColor={strokeColor} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill={`url(#${fillId})`} stroke="none" />
        <path d={linePath} fill="none" stroke={strokeColor} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
      <div className="flex items-center justify-between text-[9px] text-slate-500 mt-1">
        <span>{firstDate}</span>
        <span>{lastDate}</span>
      </div>
    </div>
  );
}

// Aug 27 2026: merges the 3 per-source trade lists (stock/NIFTY/
// BANKNIFTY) into one combined, most-recent-first table -- matches
// the single "Recent Trades" table from the mockup (spanning all
// strategies together, not 3 separate mini-tables), while the backend
// still keeps them as 3 clean separate arrays. Merge happens here on
// the frontend rather than in daily_backtest.py, since it's just a
// concat+sort+slice with no real business logic -- doesn't need a
// backend round-trip of its own.
function RecentTradesTable({ stockTrades, niftyTrades, bankniftyTrades, limit = 15 }) {
  const tagged = [
    ...(stockTrades || []).map(t => ({ ...t, source: 'Stock' })),
    ...(niftyTrades || []).map(t => ({ ...t, source: 'NIFTY' })),
    ...(bankniftyTrades || []).map(t => ({ ...t, source: 'BANKNIFTY' })),
  ];
  const merged = tagged.sort((a, b) => new Date(b.exit_dt) - new Date(a.exit_dt)).slice(0, limit);

  if (merged.length === 0) {
    return (
      <div className="rounded-lg bg-slate-800/50 border border-slate-700/40 p-4 text-center">
        <p className="text-xs text-slate-500">No resolved trades yet across any strategy.</p>
      </div>
    );
  }

  const sourceBadge = (source) => {
    const styles = {
      Stock: 'text-indigo-300 bg-indigo-500/10 border-indigo-500/25',
      NIFTY: 'text-amber-300 bg-amber-500/10 border-amber-500/25',
      BANKNIFTY: 'text-fuchsia-300 bg-fuchsia-500/10 border-fuchsia-500/25',
    };
    return styles[source] || styles.Stock;
  };

  return (
    <div className="rounded-lg bg-slate-800/50 border border-slate-700/40 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-700/40">
        <h3 className="text-sm font-bold text-white">Recent Trades</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[9px] text-slate-500 uppercase border-b border-slate-700/30">
              <th className="text-left px-4 py-2 font-medium">Date</th>
              <th className="text-left px-2 py-2 font-medium">Source</th>
              <th className="text-left px-2 py-2 font-medium">Symbol</th>
              <th className="text-left px-2 py-2 font-medium">Action</th>
              <th className="text-right px-2 py-2 font-medium">Entry</th>
              <th className="text-right px-2 py-2 font-medium">Exit</th>
              <th className="text-right px-4 py-2 font-medium">P&L</th>
            </tr>
          </thead>
          <tbody>
            {merged.map((t, i) => {
              const isWin = (t.pnl || 0) >= 0;
              return (
                <tr key={i} className="border-b border-slate-700/20 last:border-0 hover:bg-slate-900/30">
                  <td className="px-4 py-2 text-slate-400 whitespace-nowrap">
                    {new Date(t.exit_dt).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
                  </td>
                  <td className="px-2 py-2">
                    <span className={`text-[9px] px-1.5 py-0.5 rounded-full border ${sourceBadge(t.source)}`}>{t.source}</span>
                  </td>
                  <td className="px-2 py-2 text-white font-medium">{t.symbol || '—'}</td>
                  <td className="px-2 py-2 text-slate-400">{t.action || '—'}</td>
                  <td className="px-2 py-2 text-right text-slate-300 tabular-nums">{t.entry != null ? `₹${t.entry.toFixed(2)}` : '—'}</td>
                  <td className="px-2 py-2 text-right text-slate-300 tabular-nums">{t.exit_price != null ? `₹${t.exit_price.toFixed(2)}` : '—'}</td>
                  <td className={`px-4 py-2 text-right font-bold tabular-nums ${isWin ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {t.pnl != null ? `${isWin ? '+' : ''}₹${t.pnl.toFixed(2)}` : '—'}
                    {t.pnl_pct != null && <span className="text-[9px] font-normal opacity-70 ml-1">({isWin ? '+' : ''}{t.pnl_pct.toFixed(1)}%)</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SummaryCard({ title, pdfKey, summary, pdfPath, equityCurve, downloadUrl }) {
  const hasData = !!summary;
  // Aug 30 2026: downloadUrl lets a caller point this at a different
  // endpoint (the new range-report PDF) instead of the scheduled-run
  // download link every other caller still uses by default -- pdfPath
  // stays what it always was, a plain "do we have a PDF at all" gate,
  // decoupled from which URL that PDF actually lives at.
  const href = downloadUrl || `${API_BASE}/api/daily-backtest/download/${pdfKey}/`;
  return (
    <div className="rounded-lg bg-slate-800/50 border border-slate-700/40 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-white">{title}</h3>
        {pdfPath && (
          <a
            href={href}
            title={`Download ${title} report (PDF)`}
            className="w-7 h-7 flex items-center justify-center rounded-lg text-emerald-400 bg-emerald-500/10 border border-emerald-500/25 hover:bg-emerald-500/20 transition-colors"
            download
          >
            <IconDownload size={13} />
          </a>
        )}
      </div>
      {hasData && (
        <div className="mb-3 bg-slate-900/30 rounded-md p-2">
          <EquityCurveChart points={equityCurve} />
        </div>
      )}
      {!hasData ? (
        <p className="text-xs text-slate-500">No trades yet -- not enough data resolved for this report.</p>
      ) : (
        <div className="grid grid-cols-2 gap-2 text-center">
          <div className="bg-slate-900/40 rounded-md p-2">
            <p className="text-[9px] text-slate-500 uppercase">Trades</p>
            <p className="text-sm font-bold text-white">{summary.total_trades}</p>
          </div>
          <div className="bg-slate-900/40 rounded-md p-2">
            <p className="text-[9px] text-slate-500 uppercase">Net P&L</p>
            <p className={`text-sm font-bold ${(summary.net_pnl_pct || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {summary.net_pnl_pct != null ? `${summary.net_pnl_pct >= 0 ? '+' : ''}${summary.net_pnl_pct}%` : '—'}
            </p>
          </div>
          <div className="bg-slate-900/40 rounded-md p-2">
            <p className="text-[9px] text-slate-500 uppercase">Win Rate</p>
            <p className="text-sm font-bold text-white">{summary.win_rate_pct != null ? `${summary.win_rate_pct}%` : '—'}</p>
          </div>
          <div className="bg-slate-900/40 rounded-md p-2">
            <p className="text-[9px] text-slate-500 uppercase">Profit Factor</p>
            <p className="text-sm font-bold text-white">{summary.profit_factor != null ? summary.profit_factor : '—'}</p>
          </div>
        </div>
      )}
    </div>
  );
}

export default function DailyBacktestTab() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);

  const fetchStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/daily-backtest/status/`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setStatus(json);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    // 60s poll -- generous enough that it doesn't spam the endpoint,
    // frequent enough to notice a scheduled or manual run finishing
    // without needing a manual page refresh.
    const interval = setInterval(fetchStatus, 60000);
    return () => clearInterval(interval);
  }, []);

  const runNow = async () => {
    setRunning(true);
    try {
      const res = await fetch(`${API_BASE}/api/daily-backtest/run/`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // The run happens in a background thread on the server and can
      // take a while (real Fyers history calls + PDF generation) --
      // this button just confirms it STARTED, then polls status every
      // few seconds until 'started_at' moves past the moment we
      // clicked, so the cards refresh automatically once it's done
      // rather than requiring a manual re-check.
      const clickedAt = new Date().toISOString();
      const poll = setInterval(async () => {
        const r = await fetch(`${API_BASE}/api/daily-backtest/status/`);
        if (r.ok) {
          const j = await r.json();
          if (j.started_at && j.started_at > clickedAt && j.finished_at) {
            setStatus(j);
            setRunning(false);
            clearInterval(poll);
          }
        }
      }, 5000);
      // Safety timeout -- don't poll forever if something goes wrong server-side.
      setTimeout(() => { clearInterval(poll); setRunning(false); }, 10 * 60 * 1000);
    } catch (err) {
      setError(err.message);
      setRunning(false);
    }
  };

  // Aug 27 2026: date-range picker -- lets someone view performance
  // over any specific window instead of only ever seeing the last
  // scheduled/manual run's full-history numbers. rangeResult is null
  // until a range is actually queried; while null, the tab shows the
  // normal scheduled 'status' data (unchanged from before). Native
  // <input type="date"> deliberately -- no extra date-picker library
  // to add, same "don't add a dependency that can break" lesson as
  // today's reportlab issue.
  const [rangeStart, setRangeStart] = useState('');
  const [rangeEnd, setRangeEnd] = useState('');
  const [rangeResult, setRangeResult] = useState(null);
  const [rangeLoading, setRangeLoading] = useState(false);

  const viewRange = async () => {
    if (!rangeStart || !rangeEnd) return;
    setRangeLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/daily-backtest/range/?start=${rangeStart}&end=${rangeEnd}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setRangeResult(json);
    } catch (err) {
      setError(err.message);
    } finally {
      setRangeLoading(false);
    }
  };

  const clearRange = () => {
    setRangeResult(null);
    setRangeStart('');
    setRangeEnd('');
  };

  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[1, 2, 3].map(i => (
          <div key={i} className="h-40 rounded-lg bg-slate-800/30 animate-pulse border border-slate-700/30" />
        ))}
      </div>
    );
  }

  const neverRun = !status || !status.started_at;
  const isRangeView = !!rangeResult;

  // Aug 27 2026 (updated Aug 30): whichever view is active feeds the
  // SAME SummaryCard/EquityCurveChart components below. Stock now has
  // a real range-scoped PDF endpoint (see the pdfPath/downloadUrl
  // wiring on its SummaryCard below) -- NIFTY/BANKNIFTY still don't,
  // so their SummaryCards keep pdfPath=null in range view rather than
  // pointing at a stale scheduled-run PDF that wouldn't match what's
  // actually being shown.
  const displayStock = isRangeView ? rangeResult.stock : { summary: status?.stock_summary, equity_curve: status?.stock_equity_curve, recent_trades: status?.stock_recent_trades };
  const displayNifty = isRangeView ? rangeResult.nifty : { summary: status?.nifty_summary, equity_curve: status?.nifty_equity_curve, recent_trades: status?.nifty_recent_trades };
  const displayBanknifty = isRangeView ? rangeResult.banknifty : { summary: status?.banknifty_summary, equity_curve: status?.banknifty_equity_curve, recent_trades: status?.banknifty_recent_trades };

  return (
    <div className="space-y-4">
      <TabInfoBanner>
        Backtests EVERY logged signal from day one to today, not a recent window — the underlying engine
        scans every dated log file with no limit. Runs automatically ~4:00 PM (after close) and ~8:00 AM
        (before open), backfilling the last 7 days to catch anything a missed run would otherwise skip.
        The date range picker below re-slices this same full history into a specific window; it doesn't
        run a separate backtest.
      </TabInfoBanner>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-lg font-bold text-white">Daily Backtest</h2>
          <p className="text-[11px] text-slate-500">
            Runs automatically ~4:00 PM (after close) and ~8:00 AM (before open). Backfill looks back 7 days to catch anything missed.
          </p>
        </div>
        <button
          onClick={runNow}
          disabled={running}
          className={`text-xs font-medium rounded-lg px-3 py-1.5 flex items-center gap-1.5 border transition-colors ${
            running
              ? 'text-slate-500 bg-slate-800 border-slate-700 cursor-wait'
              : 'text-emerald-400 bg-emerald-500/10 border-emerald-500/25 hover:bg-emerald-500/20'
          }`}
        >
          <IconPlay size={13} /> {running ? 'Running…' : 'Run Now'}
        </button>
      </div>

      {/* Date range picker -- re-slices the SAME cards below for a
          specific window instead of always showing all-time history. */}
      <div className="flex items-center gap-2 flex-wrap bg-slate-800/30 border border-slate-700/30 rounded-lg px-3 py-2">
        <IconCalendar size={13} className="text-slate-500" />
        <span className="text-[11px] text-slate-500">Custom range:</span>
        <input
          type="date"
          value={rangeStart}
          onChange={(e) => setRangeStart(e.target.value)}
          className="h-7 text-xs bg-slate-900/60 border border-slate-700 rounded px-2 text-slate-300 focus:outline-none focus:border-emerald-500"
        />
        <span className="text-slate-600 text-xs">to</span>
        <input
          type="date"
          value={rangeEnd}
          onChange={(e) => setRangeEnd(e.target.value)}
          className="h-7 text-xs bg-slate-900/60 border border-slate-700 rounded px-2 text-slate-300 focus:outline-none focus:border-emerald-500"
        />
        <button
          onClick={viewRange}
          disabled={!rangeStart || !rangeEnd || rangeLoading}
          className="h-7 text-xs font-medium rounded px-3 text-emerald-400 bg-emerald-500/10 border border-emerald-500/25 hover:bg-emerald-500/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {rangeLoading ? 'Loading…' : 'View Range'}
        </button>
        {isRangeView && (
          <button onClick={clearRange} className="h-7 text-xs font-medium rounded px-3 text-slate-400 bg-slate-800 border border-slate-700 hover:text-slate-200 transition-colors">
            Show Latest Run
          </button>
        )}
      </div>

      {error && (
        <div className="text-xs text-amber-400 bg-amber-500/10 px-3 py-2 rounded-lg border border-amber-500/20 flex items-center gap-1.5">
          <IconAlertTriangle size={13} /> {error}
        </div>
      )}

      {isRangeView ? (
        <>
          <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
            <IconCalendar size={11} /> Showing: {rangeStart} to {rangeEnd}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Aug 30 2026: stock now has a real range-scoped PDF
                (daily_backtest.run_range_report(), same
                Scorecard/R-Multiple/every-section pipeline the full
                report uses) -- gated on displayStock.summary rather
                than a separate existence check, since the range
                endpoint and this preview endpoint filter the exact
                same trades the exact same way: if one has data the
                other will too. NIFTY/BANKNIFTY intentionally still
                get pdfPath={null} here -- no range-report endpoint
                exists for index positional backtests yet, and a
                stale full-history link would be actively misleading
                in range view (the same reasoning that set all three
                to null originally). */}
            <SummaryCard
              title="Stock Signals"
              pdfKey="stock"
              summary={displayStock.summary}
              pdfPath={displayStock.summary ? 'range-report' : null}
              downloadUrl={`${API_BASE}/api/daily-backtest/range/report/?start=${rangeStart}&end=${rangeEnd}`}
              equityCurve={displayStock.equity_curve}
            />
            <SummaryCard title="NIFTY Positional" pdfKey="nifty" summary={displayNifty.summary} pdfPath={null} equityCurve={displayNifty.equity_curve} />
            <SummaryCard title="BANKNIFTY Positional" pdfKey="banknifty" summary={displayBanknifty.summary} pdfPath={null} equityCurve={displayBanknifty.equity_curve} />
          </div>
          <RecentTradesTable stockTrades={displayStock.recent_trades} niftyTrades={displayNifty.recent_trades} bankniftyTrades={displayBanknifty.recent_trades} />
        </>
      ) : neverRun ? (
        <div className="text-center py-12">
          <div className="text-slate-600 mb-3 flex justify-center"><IconClock size={32} /></div>
          <h3 className="text-base font-bold text-white mb-1">No backtest run yet</h3>
          <p className="text-slate-400 text-sm">Wait for the next scheduled run, or hit "Run Now" above.</p>
        </div>
      ) : (
        <>
          <div className="flex items-center gap-3 text-[11px] text-slate-500 flex-wrap">
            <span className="flex items-center gap-1"><IconClock size={11} /> Last run: {new Date(status.finished_at || status.started_at).toLocaleString('en-IN')}</span>
            <span className="text-slate-600">·</span>
            <span>Trigger: {status.trigger}</span>
            <span className="text-slate-600">·</span>
            <span>Backfill: {status.backfill_range}</span>
          </div>

          {status.errors && status.errors.length > 0 && (
            <div className="text-xs text-rose-400 bg-rose-500/10 px-3 py-2 rounded-lg border border-rose-500/20">
              <p className="font-medium mb-1 flex items-center gap-1.5"><IconAlertTriangle size={13} /> {status.errors.length} step(s) had errors:</p>
              <ul className="list-disc list-inside space-y-0.5 text-rose-300/80">
                {status.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <SummaryCard title="Stock Signals" pdfKey="stock" summary={displayStock.summary} pdfPath={status.stock_pdf} equityCurve={displayStock.equity_curve} />
            <SummaryCard title="NIFTY Positional" pdfKey="nifty" summary={displayNifty.summary} pdfPath={status.nifty_pdf} equityCurve={displayNifty.equity_curve} />
            <SummaryCard title="BANKNIFTY Positional" pdfKey="banknifty" summary={displayBanknifty.summary} pdfPath={status.banknifty_pdf} equityCurve={displayBanknifty.equity_curve} />
          </div>
          <RecentTradesTable stockTrades={displayStock.recent_trades} niftyTrades={displayNifty.recent_trades} bankniftyTrades={displayBanknifty.recent_trades} />
        </>
      )}
    </div>
  );
}
