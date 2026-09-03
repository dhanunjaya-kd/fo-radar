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

function fmtVol(n) {
  if (n == null) return '—';
  // Sep 3 2026: real bug, visible directly in a real screenshot --
  // "99794K" / "135915K". Volume can genuinely run into the millions
  // for NIFTY, and this never rolled over past K, so it just kept
  // printing more and more digits instead of switching units. Now
  // escalates the same way fmtOi already does (K -> L), so large
  // volumes read the same way large OI already does elsewhere on this
  // exact chart.
  if (n >= 100000) return `${(n / 100000).toFixed(1)}L`;
  return n >= 1000 ? `${(n / 1000).toFixed(0)}K` : String(n);
}

// Sep 3 2026: per-strike PCR + sentiment -- same exact formula and
// thresholds already built and tested in StrikeOIChart.jsx (duplicated
// here rather than imported, matching this project's own established
// preference for small duplicated logic over a shared-file dependency
// -- see IconBell in App.jsx for the precedent).
function computeStrikePcr(ceOi, peOi) {
  if (!ceOi || !peOi || ceOi <= 0) return null;
  return peOi / ceOi;
}
function pcrSentimentLabel(pcr) {
  if (pcr == null) return { label: '—', color: 'text-slate-400' };
  if (pcr > 1.05) return { label: 'Bullish', color: 'text-emerald-400' };
  if (pcr < 0.95) return { label: 'Bearish', color: 'text-rose-400' };
  return { label: 'Neutral', color: 'text-amber-400' };
}

// Sep 3 2026: pulled out as its own pure function (was inline in the
// component before) -- now also carries ce_volume/pe_volume/ce_ltp/
// pe_ltp/ce_oi_chg/pe_oi_chg/ce_iv/pe_iv/ce_delta/pe_delta through,
// which the backend was already returning in ceData/peData (same raw
// fields Analytics.jsx already maps for its own table -- oi_chg_pct,
// iv, delta) but this component was silently dropping, keeping only
// `oi`. Real data that already existed, just never reached this
// component's own row shape -- not a new backend call.
function mergeOIRows(ceData, peData) {
  const byStrike = {};
  let totalCeOi = 0, totalPeOi = 0;
  for (const c of ceData || []) {
    byStrike[c.strike] = byStrike[c.strike] || { strike: c.strike, ce_oi: 0, pe_oi: 0 };
    byStrike[c.strike].ce_oi = c.oi || 0;
    byStrike[c.strike].ce_volume = c.volume ?? null;
    byStrike[c.strike].ce_ltp = c.ltp ?? null;
    byStrike[c.strike].ce_oi_chg = c.oi_chg_pct ?? null;
    byStrike[c.strike].ce_iv = c.iv ?? null;
    byStrike[c.strike].ce_delta = c.delta ?? null;
    totalCeOi += c.oi || 0;
  }
  for (const p of peData || []) {
    byStrike[p.strike] = byStrike[p.strike] || { strike: p.strike, ce_oi: 0, pe_oi: 0 };
    byStrike[p.strike].pe_oi = p.oi || 0;
    byStrike[p.strike].pe_volume = p.volume ?? null;
    byStrike[p.strike].pe_ltp = p.ltp ?? null;
    byStrike[p.strike].pe_oi_chg = p.oi_chg_pct ?? null;
    byStrike[p.strike].pe_iv = p.iv ?? null;
    byStrike[p.strike].pe_delta = p.delta ?? null;
    totalPeOi += p.oi || 0;
  }
  const rows = Object.values(byStrike).sort((a, b) => a.strike - b.strike);
  return { rows, totalCeOi, totalPeOi };
}

export default function OIDistribution() {
  const [selected, setSelected] = useState('NIFTY');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hoverIdx, setHoverIdx] = useState(null);

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
  // one row per strike -- see mergeOIRows() above.
  let rows = [];
  let totalCeOi = 0, totalPeOi = 0;
  if (data) {
    const merged = mergeOIRows(data.ceData, data.peData);
    rows = merged.rows;
    totalCeOi = merged.totalCeOi;
    totalPeOi = merged.totalPeOi;
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

          <div className="relative">
            <svg viewBox={`0 0 ${WIDTH} ${HEIGHT + 20}`} className="w-full h-auto" style={{ maxHeight: HEIGHT + 20 }}>
              {layout.bars.map((b, i) => (
                <g key={b.strike}
                   onMouseEnter={() => setHoverIdx(i)}
                   onMouseLeave={() => setHoverIdx(null)}
                   style={{ cursor: 'pointer' }}>
                  <rect x={b.ceX} y={b.ceY} width={b.barWidth} height={b.ceHeight} fill="#34d399"
                        opacity={hoverIdx === null || hoverIdx === i ? 0.85 : 0.3} />
                  <rect x={b.peX} y={b.peY} width={b.barWidth} height={b.peHeight} fill="#fb7185"
                        opacity={hoverIdx === null || hoverIdx === i ? 0.85 : 0.3} />
                  {/* invisible full-height hit area -- easier to hover accurately than the thin bars alone */}
                  <rect x={b.groupX} y="0" width={b.groupWidth} height={HEIGHT} fill="transparent" />
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

            {hoverIdx != null && rows[hoverIdx] && (() => {
              const r = rows[hoverIdx];
              const pcr = computeStrikePcr(r.ce_oi, r.pe_oi);
              const sentiment = pcrSentimentLabel(pcr);
              return (
                <div className="absolute top-1 left-1 bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-xs shadow-xl pointer-events-none min-w-[210px]">
                  <p className="text-white font-bold mb-2">Strike ₹{r.strike.toLocaleString('en-IN')}</p>

                  <p className="text-[9px] text-emerald-400 uppercase tracking-wide font-semibold mb-1">Call (CE)</p>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 mb-2">
                    <span className="text-slate-400">OI</span><span className="text-right text-slate-200">{fmtOi(r.ce_oi)}</span>
                    <span className="text-slate-400">LTP</span><span className="text-right text-slate-200">{r.ce_ltp != null ? `₹${r.ce_ltp}` : '—'}</span>
                    <span className="text-slate-400">OI Chg</span>
                    <span className={`text-right ${r.ce_oi_chg == null ? 'text-slate-200' : r.ce_oi_chg >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {r.ce_oi_chg != null ? `${r.ce_oi_chg.toFixed(1)}%` : '—'}
                    </span>
                    <span className="text-slate-400">Volume</span><span className="text-right text-slate-200">{fmtVol(r.ce_volume)}</span>
                    <span className="text-slate-400">IV</span><span className="text-right text-slate-200">{r.ce_iv != null ? `${r.ce_iv.toFixed(1)}%` : '—'}</span>
                    <span className="text-slate-400">Delta</span><span className="text-right text-slate-200">{r.ce_delta ?? '—'}</span>
                  </div>

                  <p className="text-[9px] text-rose-400 uppercase tracking-wide font-semibold mb-1">Put (PE)</p>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 mb-2">
                    <span className="text-slate-400">OI</span><span className="text-right text-slate-200">{fmtOi(r.pe_oi)}</span>
                    <span className="text-slate-400">LTP</span><span className="text-right text-slate-200">{r.pe_ltp != null ? `₹${r.pe_ltp}` : '—'}</span>
                    <span className="text-slate-400">OI Chg</span>
                    <span className={`text-right ${r.pe_oi_chg == null ? 'text-slate-200' : r.pe_oi_chg >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {r.pe_oi_chg != null ? `${r.pe_oi_chg.toFixed(1)}%` : '—'}
                    </span>
                    <span className="text-slate-400">Volume</span><span className="text-right text-slate-200">{fmtVol(r.pe_volume)}</span>
                    <span className="text-slate-400">IV</span><span className="text-right text-slate-200">{r.pe_iv != null ? `${r.pe_iv.toFixed(1)}%` : '—'}</span>
                    <span className="text-slate-400">Delta</span><span className="text-right text-slate-200">{r.pe_delta ?? '—'}</span>
                  </div>

                  <div className="flex items-center justify-between pt-1.5 border-t border-slate-700">
                    <span className="text-amber-400 font-semibold">PCR</span>
                    <span className="text-slate-200">
                      {pcr != null ? pcr.toFixed(2) : '—'} <span className={sentiment.color}>({sentiment.label})</span>
                    </span>
                  </div>
                </div>
              );
            })()}
          </div>
          <div className="flex justify-between text-[9px] text-slate-500 mt-1">
            <span>{layout.bars[0]?.strike.toLocaleString('en-IN')}</span>
            <span>{layout.bars[layout.bars.length - 1]?.strike.toLocaleString('en-IN')}</span>
          </div>
        </>
      )}
    </div>
  );
}
