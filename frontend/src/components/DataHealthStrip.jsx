import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

const STATUS_STYLE = {
  LIVE: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/25',
  DEGRADED: 'text-amber-400 bg-amber-500/10 border-amber-500/25',
  DOWN: 'text-rose-400 bg-rose-500/10 border-rose-500/25',
};

// Aug 31 2026: Section 18 (Data Health Center) from the UI Corrections
// checklist -- surfaces DataHealthView (views.py) as a compact status
// strip. Brand new component with no prior version, so nothing
// existing to conflict with. Same fetch-with-interval pattern used
// throughout this codebase (MarketHeatmap.jsx, TopLiveSignals.jsx,
// etc). Renders nothing (not a fake "OK" state) if the endpoint
// hasn't returned yet or fails -- consistent with this project's own
// no-fabrication rule.
export default function DataHealthStrip() {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const load = () => {
      fetch(`${API_BASE}/api/data-health/`)
        .then(r => (r.ok ? r.json() : null))
        .then(json => { if (mounted && json) setHealth(json); })
        .catch(() => {})
        .finally(() => { if (mounted) setLoading(false); });
    };
    load();
    const interval = setInterval(load, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (loading) {
    return <div className="h-12 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />;
  }
  if (!health) {
    return null;
  }

  const style = STATUS_STYLE[health.fyers_status] || STATUS_STYLE.DOWN;

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 px-4 py-2.5 flex items-center gap-4 flex-wrap text-xs">
      <span className={`px-2 py-1 rounded-full border font-bold whitespace-nowrap ${style}`}>
        {health.fyers_status}
      </span>
      <span className="text-slate-400">
        Source: <span className="text-slate-200">{health.source}</span>
      </span>
      <span className="text-slate-400">
        Session: <span className="text-slate-200">{health.market_session}</span>
      </span>
      <span className="text-slate-400">
        Stocks: <span className="text-slate-200">{health.stock_cache_count}/{health.stock_universe_total}</span>
        {health.missing_symbols_count > 0 && (
          <span className="text-amber-400" title={health.missing_symbols.join(', ')}>
            {' '}({health.missing_symbols_count} missing)
          </span>
        )}
      </span>
      <span className="text-slate-400">
        Updated:{' '}
        <span className="text-slate-200">
          {health.staleness_seconds != null ? `${Math.round(health.staleness_seconds)}s ago` : '—'}
        </span>
      </span>
      <span className="text-slate-400 ml-auto">
        Signals: <span className="text-slate-200">{health.live_signal_count}</span>
      </span>
    </div>
  );
}
