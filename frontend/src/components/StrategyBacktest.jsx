import { useEffect, useRef, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Aug 28 2026: tested in isolation (test_polling_logic.js) before
// being wired into this component -- correctly distinguishes
// running / genuinely complete / failed / zero-trades-but-complete,
// so the poll loop can't get stuck or stop too early.
function shouldContinuePolling(status) {
  if (!status) return true;
  return status.running === true;
}
function isRunComplete(status) {
  return status && status.running === false && status.trades !== undefined;
}
function hasRunFailed(status) {
  return status && status.running === false && status.error != null && status.trades === undefined;
}

// Same exact coordinate-transform pattern already proven for
// IndexPriceChart.jsx's equity/price chart -- reused verbatim rather
// than re-derived, since the math itself was already tested there.
function buildChartPath(values, width, height, padding = 4) {
  const clean = values.filter(v => v != null && !isNaN(v));
  if (clean.length < 2) return null;
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const range = max - min || 1;
  const usableWidth = width - padding * 2;
  const usableHeight = height - padding * 2;
  const stepX = usableWidth / (clean.length - 1);
  const coords = clean.map((v, i) => ({
    x: padding + i * stepX,
    y: padding + usableHeight - ((v - min) / range) * usableHeight,
  }));
  const path = coords.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  return { path, min, max };
}

function MetricCard({ label, value, tone }) {
  const toneClass = { emerald: 'text-emerald-400', rose: 'text-rose-400', slate: 'text-white' }[tone] || 'text-white';
  return (
    <div className="bg-slate-900/40 rounded-lg p-3 text-center">
      <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-lg font-bold tabular-nums ${toneClass}`}>{value}</p>
    </div>
  );
}

export default function StrategyBacktest() {
  const [rsiMin, setRsiMin] = useState(40);
  const [rsiMax, setRsiMax] = useState(65);
  const [adxMin, setAdxMin] = useState(25);
  const [status, setStatus] = useState(null);
  const [triggering, setTriggering] = useState(false);
  const pollRef = useRef(null);

  const poll = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/strategy-backtest/status/`);
      const data = await res.json();
      setStatus(data);
      if (shouldContinuePolling(data)) {
        pollRef.current = setTimeout(poll, 3000);
      }
    } catch (err) {
      console.error('Strategy backtest poll error:', err);
      pollRef.current = setTimeout(poll, 5000); // back off a bit longer on a genuine network error
    }
  };

  useEffect(() => {
    // Check once on mount in case a run is already in progress (e.g.
    // triggered from another tab/session) -- picks up its progress
    // rather than showing a blank "not started" state.
    poll();
    return () => { if (pollRef.current) clearTimeout(pollRef.current); };
  }, []);

  const handleRun = async () => {
    setTriggering(true);
    try {
      await fetch(`${API_BASE}/api/strategy-backtest/run/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy: { rsi_min: rsiMin, rsi_max: rsiMax, adx_min: adxMin } }),
      });
      if (pollRef.current) clearTimeout(pollRef.current);
      poll();
    } catch (err) {
      console.error('Strategy backtest trigger error:', err);
    } finally {
      setTriggering(false);
    }
  };

  const running = status?.running === true;
  const complete = isRunComplete(status);
  const failed = hasRunFailed(status);
  const metrics = complete ? status.metrics : null;
  const equityCurve = complete ? status.equity_curve : null;
  const trades = complete ? status.trades : null;

  const chart = equityCurve && equityCurve.length >= 2
    ? buildChartPath(equityCurve.map(p => p.equity), 700, 180)
    : null;

  return (
    <div className="space-y-4">
      <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
        <h3 className="text-sm font-bold text-white mb-1">Price-Action Strategy Backtest</h3>
        <p className="text-[10px] text-slate-500 mb-3">
          RSI/ADX-based rules only. OI-confirmation can't be included here -- see the strategy_backtest.py
          module docstring for why (no historical option-chain data exists for the broader F&O universe,
          only NIFTY/BANKNIFTY, and only from whenever Index Tracker snapshotting started).
        </p>

        <div className="grid grid-cols-3 gap-3 mb-3">
          <label className="text-xs text-slate-400">
            RSI Min
            <input type="number" value={rsiMin} onChange={e => setRsiMin(Number(e.target.value))}
              className="w-full mt-1 bg-slate-900/50 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-sm focus:outline-none focus:border-emerald-500" />
          </label>
          <label className="text-xs text-slate-400">
            RSI Max
            <input type="number" value={rsiMax} onChange={e => setRsiMax(Number(e.target.value))}
              className="w-full mt-1 bg-slate-900/50 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-sm focus:outline-none focus:border-emerald-500" />
          </label>
          <label className="text-xs text-slate-400">
            ADX Min
            <input type="number" value={adxMin} onChange={e => setAdxMin(Number(e.target.value))}
              className="w-full mt-1 bg-slate-900/50 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-sm focus:outline-none focus:border-emerald-500" />
          </label>
        </div>

        <button
          onClick={handleRun}
          disabled={running || triggering}
          className="w-full sm:w-auto text-sm font-medium px-4 py-2 rounded-lg bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {running ? `Running... ${status?.symbols_done ?? 0}/${status?.symbols_total ?? '?'} stocks` : triggering ? 'Starting...' : '▶ Run Backtest'}
        </button>

        {running && (
          <div className="mt-3 h-1.5 bg-slate-900/50 rounded-full overflow-hidden">
            <div
              className="h-full bg-emerald-500 transition-all"
              style={{ width: `${status.symbols_total ? (status.symbols_done / status.symbols_total) * 100 : 0}%` }}
            />
          </div>
        )}

        {failed && (
          <p className="mt-3 text-xs text-rose-400">⚠ {status.error}</p>
        )}
      </div>

      {complete && (
        <>
          {!metrics ? (
            <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4 text-center">
              <p className="text-sm text-slate-500">No trades triggered under these rules across the scanned universe. Try widening the RSI/ADX range.</p>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <MetricCard label="Trades" value={metrics.total_trades} />
                <MetricCard label="Win Rate" value={`${metrics.win_rate_pct}%`} tone={metrics.win_rate_pct >= 50 ? 'emerald' : 'rose'} />
                <MetricCard label="Net P&L" value={`${metrics.net_pnl_pct >= 0 ? '+' : ''}${metrics.net_pnl_pct}%`} tone={metrics.net_pnl_pct >= 0 ? 'emerald' : 'rose'} />
                <MetricCard label="Profit Factor" value={metrics.profit_factor ?? 'N/A'} />
              </div>

              {chart && (
                <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
                  <h4 className="text-xs font-bold text-white mb-2">Equity Curve</h4>
                  <svg viewBox="0 0 700 180" className="w-full h-auto" style={{ maxHeight: 180 }}>
                    <path d={chart.path} fill="none" stroke={metrics.net_pnl_pct >= 0 ? '#34d399' : '#fb7185'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
              )}

              {trades && trades.length > 0 && (
                <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 overflow-hidden">
                  <h4 className="text-xs font-bold text-white px-4 py-3 border-b border-slate-700/40">Trades ({trades.length})</h4>
                  <div className="overflow-x-auto max-h-80 overflow-y-auto">
                    <table className="w-full text-xs">
                      <thead className="sticky top-0 bg-slate-800">
                        <tr className="text-[9px] text-slate-500 uppercase border-b border-slate-700/30">
                          <th className="text-left px-3 py-2">Symbol</th>
                          <th className="text-right px-3 py-2">Entry</th>
                          <th className="text-right px-3 py-2">Exit</th>
                          <th className="text-right px-3 py-2">P&L</th>
                          <th className="text-center px-3 py-2">Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {trades.map((t, i) => (
                          <tr key={i} className="border-b border-slate-700/20 last:border-0">
                            <td className="px-3 py-1.5 text-white font-medium whitespace-nowrap">{t.symbol}</td>
                            <td className="px-3 py-1.5 text-right text-slate-300 tabular-nums">₹{t.entry_price}</td>
                            <td className="px-3 py-1.5 text-right text-slate-300 tabular-nums">₹{t.exit_price}</td>
                            <td className={`px-3 py-1.5 text-right font-medium tabular-nums ${t.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                              {t.pnl >= 0 ? '+' : ''}₹{t.pnl.toLocaleString('en-IN')}
                            </td>
                            <td className="px-3 py-1.5 text-center text-slate-400 whitespace-nowrap">{t.exit_reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
