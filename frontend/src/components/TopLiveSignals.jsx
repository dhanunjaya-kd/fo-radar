import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

const GRADE_STYLES = {
  'A+': 'text-emerald-400 bg-emerald-500/10',
  'A': 'text-emerald-400 bg-emerald-500/10',
  'B': 'text-lime-400 bg-lime-500/10',
  'C': 'text-amber-400 bg-amber-500/10',
  'D': 'text-rose-400 bg-rose-500/10',
};

// Aug 28 2026: tested (test_status_style.js) against the exact real
// outcome_status strings views.py's _build_all() produces -- "Open",
// "Target N Hit" (N = 1/2/3), "SL Hit". NOT the mockup's "Confirmed/
// Active" split, which doesn't correspond to any real varying field
// in this data (every signal reaching this list is already OI-
// confirmed by the qualifying filter itself, so that would always
// read the same for every row -- outcome_status genuinely varies).
function statusStyle(status) {
  if (status === 'Open') return 'text-blue-400 bg-blue-500/10 border-blue-500/25';
  if (status === 'SL Hit') return 'text-rose-400 bg-rose-500/10 border-rose-500/25';
  if (status && status.startsWith('Target')) return 'text-emerald-400 bg-emerald-500/10 border-emerald-500/25';
  return 'text-slate-400 bg-slate-500/10 border-slate-500/25'; // unknown/fallback -- never crash on an unexpected value
}

export default function TopLiveSignals({ onViewAll, limit = 5 }) {
  const [signals, setSignals] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const fetchSignals = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/sniper-only/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        // Aug 30 2026: SignalList.jsx already dedupes /api/sniper-only/
        // by symbol before rendering it -- this widget hits the exact
        // same endpoint but never had the same guard, which is why a
        // repeated symbol (e.g. LODHA) could show twice here while
        // Live Signals stayed clean. Same filter, same precedent.
        const seen = new Set();
        const unique = (json.signals || []).filter(s => {
          if (seen.has(s.symbol)) return false;
          seen.add(s.symbol);
          return true;
        });
        if (mounted) setSignals(unique);
      } catch (err) {
        console.error('Top live signals fetch error:', err);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchSignals();
    // Same 60s cadence SignalList.jsx already uses for this same endpoint.
    const interval = setInterval(fetchSignals, 60000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (loading) {
    return <div className="h-64 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />;
  }

  const topSignals = (signals || []).slice(0, limit);

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/40">
        <h3 className="text-sm font-bold text-white flex items-center gap-1.5">
          <span className="text-amber-500">⚡</span> Top Live Signals
        </h3>
        {onViewAll && (
          <button onClick={onViewAll} className="text-[11px] text-blue-400 hover:text-blue-300 transition-colors">
            View All →
          </button>
        )}
      </div>

      {topSignals.length === 0 ? (
        <div className="p-6 text-center">
          <p className="text-sm text-slate-500">No qualifying signals right now.</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[9px] text-slate-500 uppercase border-b border-slate-700/30">
                <th className="text-left px-4 py-2 font-medium">Symbol</th>
                <th className="text-right px-2 py-2 font-medium">Price</th>
                <th className="text-right px-2 py-2 font-medium">Chg%</th>
                <th className="text-center px-2 py-2 font-medium">Grade</th>
                <th className="text-right px-2 py-2 font-medium">Entry</th>
                <th className="text-right px-2 py-2 font-medium">SL</th>
                <th className="text-center px-2 py-2 font-medium">Status</th>
                <th className="text-center px-4 py-2 font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {topSignals.map((s) => {
                const isPos = (s.change_percent || 0) >= 0;
                const isBuy = s.action === 'BUY';
                return (
                  <tr key={s.symbol} className="border-b border-slate-700/20 last:border-0 hover:bg-slate-900/30">
                    <td className="px-4 py-2 text-white font-medium whitespace-nowrap">{s.symbol}</td>
                    <td className="px-2 py-2 text-right text-slate-300 tabular-nums">₹{s.price != null ? s.price.toFixed(2) : '—'}</td>
                    <td className={`px-2 py-2 text-right font-medium tabular-nums ${isPos ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {isPos ? '+' : ''}{s.change_percent != null ? s.change_percent.toFixed(2) : '0.00'}%
                    </td>
                    <td className="px-2 py-2 text-center">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${GRADE_STYLES[s.grade] || GRADE_STYLES['C']}`}>{s.grade}</span>
                    </td>
                    <td className="px-2 py-2 text-right text-slate-300 tabular-nums">₹{s.entry != null ? s.entry.toFixed(2) : '—'}</td>
                    <td className="px-2 py-2 text-right text-rose-400/80 tabular-nums">₹{s.sl != null ? s.sl.toFixed(2) : '—'}</td>
                    <td className="px-2 py-2 text-center">
                      <span className={`text-[9px] px-1.5 py-0.5 rounded-full border whitespace-nowrap ${statusStyle(s.outcome_status)}`}>{s.outcome_status || 'Open'}</span>
                    </td>
                    <td className="px-4 py-2 text-center">
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${isBuy ? 'text-emerald-400 bg-emerald-500/10' : 'text-rose-400 bg-rose-500/10'}`}>
                        {isBuy ? 'BUY' : 'SELL'}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
