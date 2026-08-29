import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Aug 28 2026: tested in test_condense_sectors.js -- sectors is
// already sorted best-first by the backend (_compute_sector_performance),
// this just takes slices. When there aren't enough sectors to
// meaningfully split, bottom stays empty rather than duplicating the
// same sector as both a top AND bottom performer.
function condenseSectors(sectors, n = 3) {
  if (!sectors || sectors.length === 0) return { top: [], bottom: [] };
  if (sectors.length <= n) return { top: sectors, bottom: [] };
  const top = sectors.slice(0, n);
  const bottom = sectors.slice(-n).reverse();
  return { top, bottom };
}

export default function SectorStrength({ onNavigate }) {
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
        console.error('Sector strength fetch error:', err);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (loading) {
    return <div className="h-32 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />;
  }

  const { top, bottom } = condenseSectors(sectors || []);

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-white">Sector Strength</h3>
        {onNavigate && (
          <button onClick={() => onNavigate('market')} className="text-[11px] text-blue-400 hover:text-blue-300">
            View All →
          </button>
        )}
      </div>
      {top.length === 0 ? (
        <p className="text-xs text-slate-500 text-center py-3">No sector data yet.</p>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="text-[9px] text-emerald-400 uppercase tracking-wider mb-1.5">Leading</p>
            <div className="space-y-1">
              {top.map(s => (
                <div key={s.sector} className="flex items-center justify-between text-xs">
                  <span className="text-slate-300">{s.sector}</span>
                  <span className="text-emerald-400 font-semibold tabular-nums">+{s.change_percent.toFixed(2)}%</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <p className="text-[9px] text-rose-400 uppercase tracking-wider mb-1.5">Lagging</p>
            <div className="space-y-1">
              {bottom.length === 0 ? (
                <p className="text-[10px] text-slate-600">—</p>
              ) : bottom.map(s => (
                <div key={s.sector} className="flex items-center justify-between text-xs">
                  <span className="text-slate-300">{s.sector}</span>
                  <span className="text-rose-400 font-semibold tabular-nums">{s.change_percent.toFixed(2)}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
