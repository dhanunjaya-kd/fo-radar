import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Aug 31 2026: P0-6 (NO TRADE state) from the UI Corrections
// checklist -- surfaces NoTradeLogView (views.py). Genuinely fills
// the slot AttentionFeed used to occupy on the Dashboard (removed
// earlier this session for showing the same signals as
// TopLiveSignals) but with something TopLiveSignals structurally
// can't show: WHY candidates are being rejected right now, not which
// ones qualified. Brand new component, nothing existing touched.
export default function NoTradeLog() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const load = () => {
      fetch(`${API_BASE}/api/no-trade-log/`)
        .then(r => (r.ok ? r.json() : null))
        .then(json => { if (mounted && json) setData(json); })
        .catch(() => {})
        .finally(() => { if (mounted) setLoading(false); });
    };
    load();
    const interval = setInterval(load, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/40">
        <h3 className="text-sm font-bold text-white flex items-center gap-1.5">
          <span className="text-amber-500">⛔</span> No Trade — This Cycle
        </h3>
        {data && <span className="text-[11px] text-slate-500">{data.count} rejected</span>}
      </div>
      <div className="p-3 max-h-64 overflow-y-auto">
        {loading && <div className="py-6 text-center text-slate-500 text-sm">Loading…</div>}
        {!loading && (!data || data.rejected.length === 0) && (
          <div className="py-6 text-center text-slate-500 text-sm">
            Nothing rejected this cycle — either everything's qualifying, or the scanner hasn't completed a pass yet.
          </div>
        )}
        {!loading && data && data.rejected.length > 0 && (
          <ul className="space-y-1.5">
            {data.rejected.slice(0, 10).map((r, i) => (
              <li key={r.symbol + i} className="flex items-start gap-2 text-xs">
                <span className="text-white font-medium shrink-0 w-20 truncate">{r.symbol}</span>
                <span className="text-slate-400">{r.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
