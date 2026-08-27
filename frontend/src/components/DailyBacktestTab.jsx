import { useEffect, useState } from 'react';

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

function SummaryCard({ title, pdfKey, summary, pdfPath, equityCurve }) {
  const hasData = !!summary;
  return (
    <div className="rounded-lg bg-slate-800/50 border border-slate-700/40 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-white">{title}</h3>
        {pdfPath && (
          <a
            href={`${API_BASE}/api/daily-backtest/download/${pdfKey}/`}
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

  return (
    <div className="space-y-4">
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

      {error && (
        <div className="text-xs text-amber-400 bg-amber-500/10 px-3 py-2 rounded-lg border border-amber-500/20 flex items-center gap-1.5">
          <IconAlertTriangle size={13} /> {error}
        </div>
      )}

      {neverRun ? (
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
            <SummaryCard title="Stock Signals" pdfKey="stock" summary={status.stock_summary} pdfPath={status.stock_pdf} equityCurve={status.stock_equity_curve} />
            <SummaryCard title="NIFTY Positional" pdfKey="nifty" summary={status.nifty_summary} pdfPath={status.nifty_pdf} equityCurve={status.nifty_equity_curve} />
            <SummaryCard title="BANKNIFTY Positional" pdfKey="banknifty" summary={status.banknifty_summary} pdfPath={status.banknifty_pdf} equityCurve={status.banknifty_equity_curve} />
          </div>
        </>
      )}
    </div>
  );
}
