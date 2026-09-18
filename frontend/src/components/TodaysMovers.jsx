import { useState, useEffect } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

/**
 * Sep 18 2026: displays /api/todays-movers/ as-is. That endpoint's own
 * docstring explains the ranking design (percentile rank on price
 * move, relative volume, and traded value; a stock's overall rank is
 * the max of the three, so it surfaces if it's unusual on ANY one
 * dimension) -- this component adds no ranking logic of its own, just
 * renders each stock's own stated "why" tags next to its real numbers.
 */
export default function TodaysMovers() {
  const [movers, setMovers] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/todays-movers/?limit=12`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (!cancelled) { setMovers(json.movers || []); setError(false); }
      } catch (err) {
        console.error('TodaysMovers fetch error:', err);
        if (!cancelled) setError(true);
      }
    };
    load();
    const interval = setInterval(load, 60000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm font-semibold text-white">Today's Movers</span>
        <span className="text-[11px] text-slate-500">Ranked by price, relative volume and traded value across the loaded universe.</span>
      </div>
      <div className="text-[11px] text-slate-500 mb-3">
        Unusual activity, regardless of direction — where participation, volume, or turnover was abnormal. A stock can lead this list while finishing flat.
      </div>

      {error && <div className="text-sm text-slate-500">Movers data unavailable right now.</div>}
      {!error && !movers && <div className="text-sm text-slate-500">Loading…</div>}
      {!error && movers && movers.length === 0 && <div className="text-sm text-slate-500">No stock data loaded yet.</div>}

      {!error && movers && movers.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[11px] text-slate-500 border-b border-slate-800">
                <th className="text-left pb-2 pr-3">Symbol</th>
                <th className="text-right pb-2 pr-3">Price</th>
                <th className="text-right pb-2 pr-3">Change</th>
                <th className="text-right pb-2 pr-3">Rel. Vol</th>
                <th className="text-left pb-2">Why</th>
              </tr>
            </thead>
            <tbody>
              {movers.map(m => (
                <tr key={m.symbol} className="border-b border-slate-800/50">
                  <td className="py-1.5 pr-3 font-medium text-white">{m.symbol}</td>
                  <td className="py-1.5 pr-3 text-right text-slate-300">{m.price.toFixed(2)}</td>
                  <td className={`py-1.5 pr-3 text-right font-medium ${m.change_percent >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {m.change_percent >= 0 ? '+' : ''}{m.change_percent.toFixed(2)}%
                  </td>
                  <td className="py-1.5 pr-3 text-right text-slate-400">
                    {m.relative_volume != null ? `${m.relative_volume.toFixed(1)}x` : '—'}
                  </td>
                  <td className="py-1.5 text-slate-500 text-[11px]">{m.why.join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
