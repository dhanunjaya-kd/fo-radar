import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Aug 28 2026: display order for whichever indices actually come back
// -- doesn't assume all 4 resolve (see BroaderIndicesView/
// fetch_broader_indices() in views.py: these symbols are unverified
// against a live Fyers connection, some may simply be absent).
const DISPLAY_ORDER = ['NIFTY Next 50', 'NIFTY 100', 'NIFTY Midcap 100', 'NIFTY Smallcap 100'];

export default function IndicesPerformance() {
  const [indices, setIndices] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/broader-indices/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (mounted) setIndices(json.indices || {});
      } catch (err) {
        console.error('Broader indices fetch error:', err);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchData();
    // Slower cadence than the 30s market-summary panels -- this makes
    // its own live Fyers call every time (see the backend docstring),
    // and these broader indices move less urgently than NIFTY/
    // BANKNIFTY themselves.
    const interval = setInterval(fetchData, 60000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (loading) {
    return <div className="h-40 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />;
  }

  const resolved = DISPLAY_ORDER.filter(name => indices && indices[name]);

  if (resolved.length === 0) {
    return (
      <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
        <h3 className="text-sm font-bold text-white mb-1">Indices Performance</h3>
        <p className="text-xs text-slate-500">
          None of these broader indices resolved from Fyers right now -- the exact symbols
          (NIFTYNXT50, NIFTY100, NIFTYMIDCAP100, NIFTYSMLCAP100) haven't been confirmed against
          a live connection yet.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-700/40">
        <h3 className="text-sm font-bold text-white">Indices Performance</h3>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[9px] text-slate-500 uppercase border-b border-slate-700/30">
            <th className="text-left px-4 py-2 font-medium">Index</th>
            <th className="text-right px-2 py-2 font-medium">Price</th>
            <th className="text-right px-4 py-2 font-medium">Chg%</th>
          </tr>
        </thead>
        <tbody>
          {resolved.map((name) => {
            const idx = indices[name];
            const isPos = idx.change_percent >= 0;
            return (
              <tr key={name} className="border-b border-slate-700/20 last:border-0 hover:bg-slate-900/30">
                <td className="px-4 py-2 text-white font-medium whitespace-nowrap">{name}</td>
                <td className="px-2 py-2 text-right text-slate-300 tabular-nums">{idx.price.toLocaleString('en-IN')}</td>
                <td className={`px-4 py-2 text-right font-bold tabular-nums ${isPos ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {isPos ? '+' : ''}{idx.change_percent.toFixed(2)}%
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {resolved.length < DISPLAY_ORDER.length && (
        <p className="text-[10px] text-slate-600 px-4 py-2 border-t border-slate-700/30">
          {DISPLAY_ORDER.length - resolved.length} of {DISPLAY_ORDER.length} indices didn't resolve from Fyers this cycle.
        </p>
      )}
    </div>
  );
}
