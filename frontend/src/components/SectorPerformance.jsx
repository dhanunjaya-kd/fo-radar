import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

export default function SectorPerformance() {
  const [sectors, setSectors] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/market-summary/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (mounted) setSectors(json.sectors || []);
      } catch (err) {
        console.error('Sector performance fetch error:', err);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchData();
    // Same 30s cadence as MarketBanner/MarketBreadth -- reads the exact
    // same market-summary response, just a different field.
    const interval = setInterval(fetchData, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (loading) {
    return <div className="h-64 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />;
  }

  if (!sectors || sectors.length === 0) {
    return (
      <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-6 text-center">
        <p className="text-sm text-slate-500">No sector data yet -- waiting for the first scan cycle.</p>
      </div>
    );
  }

  // Widest real |change_percent| across all sectors this cycle, used to
  // scale every bar's width relative to the day's actual spread rather
  // than a fixed arbitrary cap -- a quiet day (all sectors within
  // +-0.5%) still shows visible differences between bars instead of
  // every bar looking identically tiny against a fixed +-5% scale.
  const maxAbs = Math.max(0.1, ...sectors.map(s => Math.abs(s.change_percent)));

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-700/40">
        <h3 className="text-sm font-bold text-white">Sector Performance</h3>
        <p className="text-[10px] text-slate-500 mt-0.5">Simple average change% across each sector's F&O stocks -- not a market-cap-weighted index</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[9px] text-slate-500 uppercase border-b border-slate-700/30">
              <th className="text-left px-4 py-2 font-medium">Sector</th>
              <th className="text-right px-2 py-2 font-medium">Chg%</th>
              <th className="text-center px-2 py-2 font-medium">Adv/Dec</th>
              <th className="text-left px-4 py-2 font-medium w-1/3">Performance</th>
            </tr>
          </thead>
          <tbody>
            {sectors.map((s) => {
              const isPos = s.change_percent >= 0;
              const barWidthPct = Math.min(100, (Math.abs(s.change_percent) / maxAbs) * 100);
              return (
                <tr key={s.sector} className="border-b border-slate-700/20 last:border-0 hover:bg-slate-900/30">
                  <td className="px-4 py-2 text-white font-medium whitespace-nowrap">{s.sector}</td>
                  <td className={`px-2 py-2 text-right font-bold tabular-nums ${isPos ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {isPos ? '+' : ''}{s.change_percent.toFixed(2)}%
                  </td>
                  <td className="px-2 py-2 text-center text-slate-400 whitespace-nowrap">
                    <span className="text-emerald-400">{s.advances}</span>
                    {' / '}
                    <span className="text-rose-400">{s.declines}</span>
                  </td>
                  <td className="px-4 py-2">
                    {/* Bar grows from the CENTER -- right for positive,
                        left for negative -- so magnitude and direction
                        are both visible at a glance, same convention as
                        a real advance/decline bar chart. */}
                    <div className="relative h-2 bg-slate-900/50 rounded-full overflow-hidden">
                      <div className="absolute left-1/2 top-0 h-full w-px bg-slate-600" />
                      <div
                        className={`absolute top-0 h-full ${isPos ? 'bg-emerald-500' : 'bg-rose-500'}`}
                        style={
                          isPos
                            ? { left: '50%', width: `${barWidthPct / 2}%` }
                            : { right: '50%', width: `${barWidthPct / 2}%` }
                        }
                      />
                    </div>
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
