import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Aug 28 2026: layout math verified in test_oi_distribution.js before
// this component was written -- correct scaling to the true global
// max, no overlapping strike groups, and Max Pain correctly snaps to
// the nearest real strike rather than erroring when it falls between
// listed strikes.
function computeOIDistributionLayout(rows, maxPain, width, height) {
  if (rows.length === 0) return null;
  const maxOi = Math.max(...rows.flatMap(r => [r.ce_oi || 0, r.pe_oi || 0]), 1);
  const barGroupWidth = width / rows.length;
  const barWidth = barGroupWidth * 0.35;

  const bars = rows.map((r, i) => {
    const groupX = i * barGroupWidth;
    const ceHeight = ((r.ce_oi || 0) / maxOi) * height;
    const peHeight = ((r.pe_oi || 0) / maxOi) * height;
    return {
      strike: r.strike,
      ceX: groupX + barGroupWidth * 0.15, ceY: height - ceHeight, ceHeight,
      peX: groupX + barGroupWidth * 0.55, peY: height - peHeight, peHeight,
      barWidth, groupX, groupWidth: barGroupWidth,
    };
  });

  let maxPainX = null;
  if (maxPain != null) {
    const closestIdx = rows.reduce((closestI, r, i) =>
      Math.abs(r.strike - maxPain) < Math.abs(rows[closestI].strike - maxPain) ? i : closestI, 0);
    maxPainX = closestIdx * barGroupWidth + barGroupWidth / 2;
  }

  return { bars, maxPainX, maxOi };
}

function fmtOi(n) {
  if (n == null) return '—';
  return `${(n / 100000).toFixed(1)}L`;
}

export default function OIDistribution() {
  const [selected, setSelected] = useState('NIFTY');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);
    const fetchData = async () => {
      try {
        // Same /api/option-analytics/<symbol>/ endpoint already fixed
        // earlier tonight to support NIFTY/BANKNIFTY -- no new backend
        // work needed for this panel at all.
        const res = await fetch(`${API_BASE}/api/option-analytics/${selected}/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (mounted) {
          if (json.live === false) {
            setError(json.error || 'No live data available right now.');
            setData(null);
          } else {
            setData(json);
          }
        }
      } catch (err) {
        if (mounted) { console.error('OI distribution fetch error:', err); setError(err.message); }
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, [selected]);

  const WIDTH = 700, HEIGHT = 220;

  // Merge ceData/peData (each a flat list of {strike, oi, ...}) into
  // one row per strike -- the shape computeOIDistributionLayout wants.
  let rows = [];
  let totalCeOi = 0, totalPeOi = 0;
  if (data) {
    const byStrike = {};
    for (const c of data.ceData || []) {
      byStrike[c.strike] = byStrike[c.strike] || { strike: c.strike, ce_oi: 0, pe_oi: 0 };
      byStrike[c.strike].ce_oi = c.oi || 0;
      totalCeOi += c.oi || 0;
    }
    for (const p of data.peData || []) {
      byStrike[p.strike] = byStrike[p.strike] || { strike: p.strike, ce_oi: 0, pe_oi: 0 };
      byStrike[p.strike].pe_oi = p.oi || 0;
      totalPeOi += p.oi || 0;
    }
    rows = Object.values(byStrike).sort((a, b) => a.strike - b.strike);
  }
  const layout = rows.length > 0 ? computeOIDistributionLayout(rows, data?.maxPain, WIDTH, HEIGHT) : null;
  const totalOi = totalCeOi + totalPeOi;

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-white">OI Distribution</h3>
        <div className="flex gap-1 bg-slate-900/50 p-0.5 rounded-lg">
          {['NIFTY', 'BANKNIFTY'].map(idx => (
            <button
              key={idx}
              onClick={() => setSelected(idx)}
              className={`text-[11px] font-medium px-2.5 py-1 rounded-md transition-colors ${
                selected === idx ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {idx}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="h-56 rounded-lg bg-slate-900/30 animate-pulse" />
      ) : error || !layout ? (
        <div className="py-8 text-center">
          <p className="text-sm text-slate-500">{error || 'No live option chain available right now.'}</p>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-center gap-6 mb-2 text-xs">
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm bg-emerald-500" />
              <span className="text-slate-400">Call OI</span>
              <span className="text-white font-medium">{fmtOi(totalCeOi)}</span>
              <span className="text-slate-500">({totalOi ? ((totalCeOi / totalOi) * 100).toFixed(0) : 0}%)</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm bg-rose-500" />
              <span className="text-slate-400">Put OI</span>
              <span className="text-white font-medium">{fmtOi(totalPeOi)}</span>
              <span className="text-slate-500">({totalOi ? ((totalPeOi / totalOi) * 100).toFixed(0) : 0}%)</span>
            </span>
          </div>

          <svg viewBox={`0 0 ${WIDTH} ${HEIGHT + 20}`} className="w-full h-auto" style={{ maxHeight: HEIGHT + 20 }}>
            {layout.bars.map((b) => (
              <g key={b.strike}>
                <rect x={b.ceX} y={b.ceY} width={b.barWidth} height={b.ceHeight} fill="#34d399" opacity="0.85" />
                <rect x={b.peX} y={b.peY} width={b.barWidth} height={b.peHeight} fill="#fb7185" opacity="0.85" />
              </g>
            ))}
            {layout.maxPainX != null && (
              <>
                <line x1={layout.maxPainX} y1="0" x2={layout.maxPainX} y2={HEIGHT} stroke="#fbbf24" strokeWidth="1.5" strokeDasharray="4,3" />
                <text x={layout.maxPainX} y={HEIGHT + 14} textAnchor="middle" fill="#fbbf24" fontSize="10">
                  Max Pain {data.maxPain?.toLocaleString('en-IN')}
                </text>
              </>
            )}
          </svg>
          <div className="flex justify-between text-[9px] text-slate-500 mt-1">
            <span>{layout.bars[0]?.strike.toLocaleString('en-IN')}</span>
            <span>{layout.bars[layout.bars.length - 1]?.strike.toLocaleString('en-IN')}</span>
          </div>
        </>
      )}
    </div>
  );
}
