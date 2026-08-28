import { useEffect, useState } from 'react';

// Relative on purpose -- same note as MarketBanner.jsx/SignalList.jsx.
const API_BASE = import.meta.env.VITE_API_URL || '';

const IconTrendingUp = ({ size = 14 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
);
const IconTrendingDown = ({ size = 14 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg>
);
const IconMinus = ({ size = 14 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"/></svg>
);
const IconBarChart = ({ size = 14 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/></svg>
);

// Aug 28 2026: Crore-formatted volume, matching the en-IN convention
// already used throughout this project (fmt() in MarketBanner.jsx/
// SniperCard.jsx). Volume here is a real SHARE count summed across the
// F&O universe (see views.py's _compute_breadth) -- not currency, so
// this is "X.XX Cr shares", the same numbering grouping as money just
// without a currency symbol.
const formatVolume = (v) => {
  if (v == null || isNaN(v)) return '—';
  const crores = v / 10000000;
  if (crores >= 1) return `${crores.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} Cr`;
  const lakhs = v / 100000;
  return `${lakhs.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} L`;
};

function StatCard({ icon, label, value, pct, tone }) {
  const toneClasses = {
    emerald: 'text-emerald-400 bg-emerald-500/10',
    rose: 'text-rose-400 bg-rose-500/10',
    slate: 'text-slate-400 bg-slate-500/10',
    indigo: 'text-indigo-400 bg-indigo-500/10',
  }[tone] || 'text-slate-400 bg-slate-500/10';

  return (
    <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-800/60 border border-slate-700/50">
      <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${toneClasses}`}>
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">{label}</p>
        <div className="flex items-baseline gap-1.5">
          <p className="text-lg font-bold text-white tabular-nums">{value}</p>
          {pct != null && <span className="text-[11px] text-slate-500">{pct}%</span>}
        </div>
      </div>
    </div>
  );
}

export default function MarketBreadth() {
  const [breadth, setBreadth] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/market-summary/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (mounted) setBreadth(json.breadth || null);
      } catch (err) {
        console.error('Market breadth fetch error:', err);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchData();
    // Same 30s cadence as MarketBanner.jsx's own market-summary poll --
    // this reads from the exact same endpoint/response, just a
    // different field, so there's no reason to poll independently at
    // a different interval.
    const interval = setInterval(fetchData, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (loading || !breadth) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        {[1, 2, 3, 4].map(i => (
          <div key={i} className="h-16 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />
        ))}
      </div>
    );
  }

  const { advances, declines, unchanged, advances_pct, declines_pct, unchanged_pct, total, total_volume } = breadth;

  return (
    <div className="mb-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-2">
        <StatCard icon={<IconTrendingUp size={15} />} label="Advances" value={advances.toLocaleString('en-IN')} pct={advances_pct} tone="emerald" />
        <StatCard icon={<IconTrendingDown size={15} />} label="Declines" value={declines.toLocaleString('en-IN')} pct={declines_pct} tone="rose" />
        <StatCard icon={<IconMinus size={15} />} label="Unchanged" value={unchanged.toLocaleString('en-IN')} pct={unchanged_pct} tone="slate" />
        <StatCard icon={<IconBarChart size={15} />} label="Total Volume" value={formatVolume(total_volume)} pct={null} tone="indigo" />
      </div>

      {/* Segmented breadth bar -- green/red/gray widths match the real
          advances/declines/unchanged percentages above, not a separate
          computation. */}
      <div className="flex items-center gap-2 px-1">
        <span className="text-[9px] text-slate-500 uppercase tracking-wider shrink-0">Breadth</span>
        <div className="flex-1 h-1.5 rounded-full overflow-hidden bg-slate-800 flex">
          <div className="bg-emerald-500 h-full" style={{ width: `${advances_pct}%` }} />
          <div className="bg-slate-600 h-full" style={{ width: `${unchanged_pct}%` }} />
          <div className="bg-rose-500 h-full" style={{ width: `${declines_pct}%` }} />
        </div>
        <span className="text-[9px] text-slate-500 shrink-0">{total} F&O stocks</span>
      </div>
    </div>
  );
}
