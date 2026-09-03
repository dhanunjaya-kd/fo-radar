import { useState } from 'react';

// Sep 3 2026: built for the "NIFTY OI Positioning" -> full OI Analytics
// page, styled after an Opstra-style strike-by-strike OI chart. Pure
// presentation -- ceData/peData are already fetched and mapped in
// Analytics.jsx (real Fyers option-chain data, already flowing to the
// existing table below this chart); this component adds no new fetch,
// no new backend call, nothing that depends on any external site --
// exactly the kind of change that can be fully tested before delivery,
// unlike the two failed external-link attempts earlier this session.
//
// Scope, deliberately: strike-by-strike CE/PE OI bars + a per-strike
// PCR line + hover tooltip (OI, LTP, per-strike PCR, Delta/Theta/Vega
// -- all fields ceData/peData already carry). Does NOT include the
// historical date-slider or 3min/15min/30min/Daily granularity toggle
// Opstra also has -- that needs new backend work (logging full
// per-strike snapshots over time, which this project doesn't do yet),
// scoped separately on purpose rather than promised here.

// Per-strike PCR -- pe.oi / ce.oi. Null when either side is missing or
// zero (never a divide-by-zero NaN/Infinity slipping into the chart).
function computeStrikePcr(ce, pe) {
  if (!ce || !pe || !ce.oi || !pe.oi || ce.oi <= 0) return null;
  return pe.oi / ce.oi;
}

// Pure layout function -- no DOM, no React -- so it can be unit tested
// with synthetic ceData/peData directly, same principle as
// IndexPriceChart.jsx's buildChartPath().
function buildBarLayout(ceData, peData, width, height, padding = 28) {
  const n = ceData.length;
  if (n === 0) return null;

  const maxOi = Math.max(1, ...ceData.map(d => d.oi || 0), ...peData.map(d => d.oi || 0));
  const usableWidth = width - padding * 2;
  const usableHeight = height - padding * 2;
  const slotWidth = usableWidth / n;
  const barWidth = Math.max(2, slotWidth * 0.38);

  const bars = ceData.map((ce, i) => {
    const pe = peData[i];
    const slotX = padding + i * slotWidth;
    const ceH = ((ce.oi || 0) / maxOi) * usableHeight;
    const peH = ((pe?.oi || 0) / maxOi) * usableHeight;
    return {
      strike: ce.strike,
      ceX: slotX + slotWidth * 0.08,
      peX: slotX + slotWidth * 0.54,
      barWidth,
      ceY: padding + usableHeight - ceH,
      peY: padding + usableHeight - peH,
      ceH, peH,
      centerX: slotX + slotWidth / 2,
    };
  });

  return { bars, maxOi, slotWidth };
}

// PCR line path -- secondary y-scale (0 to maxPcr, independent of the
// OI bars' own scale), only across strikes with a real, non-null PCR.
function buildPcrLinePath(ceData, peData, bars, height, padding = 28) {
  const pcrs = ceData.map((ce, i) => ({ x: bars[i].centerX, pcr: computeStrikePcr(ce, peData[i]) }))
    .filter(p => p.pcr != null);
  if (pcrs.length < 2) return null;

  const maxPcr = Math.max(1, ...pcrs.map(p => p.pcr)) * 1.1;
  const usableHeight = height - padding * 2;
  const points = pcrs.map(p => ({
    x: p.x,
    y: padding + usableHeight - (p.pcr / maxPcr) * usableHeight,
  }));
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  return { path, maxPcr, points };
}

function fmtLots(n) {
  if (n == null) return '—';
  return n >= 100000 ? `${(n / 100000).toFixed(1)}L` : n.toLocaleString('en-IN');
}

export default function StrikeOIChart({ ceData, peData, atmStrike }) {
  const [hoverIdx, setHoverIdx] = useState(null);

  const WIDTH = 700, HEIGHT = 260;
  if (!ceData || !peData || ceData.length === 0) return null;

  const layout = buildBarLayout(ceData, peData, WIDTH, HEIGHT);
  if (!layout) return null;
  const pcrLine = buildPcrLinePath(ceData, peData, layout.bars, HEIGHT);

  const hovered = hoverIdx != null ? {
    ce: ceData[hoverIdx], pe: peData[hoverIdx], bar: layout.bars[hoverIdx],
    pcr: computeStrikePcr(ceData[hoverIdx], peData[hoverIdx]),
  } : null;

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 p-6 mb-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-bold text-white">Strike-wise OI Positioning</h3>
        <div className="flex items-center gap-3 text-[10px] text-slate-500">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-400 inline-block" /> Call OI</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-rose-400 inline-block" /> Put OI</span>
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-amber-400 inline-block" /> PCR</span>
        </div>
      </div>

      <div className="relative">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full h-auto" style={{ maxHeight: HEIGHT }}>
          {layout.bars.map((bar, i) => {
            const isATM = bar.strike === atmStrike;
            return (
              <g key={bar.strike}
                 onMouseEnter={() => setHoverIdx(i)}
                 onMouseLeave={() => setHoverIdx(null)}
                 style={{ cursor: 'pointer' }}>
                {isATM && (
                  <rect x={bar.centerX - layout.slotWidth / 2} y={0} width={layout.slotWidth} height={HEIGHT}
                        fill="#3b82f6" opacity={hoverIdx === i ? 0.12 : 0.06} />
                )}
                <rect x={bar.ceX} y={bar.ceY} width={bar.barWidth} height={bar.ceH}
                      fill="#34d399" opacity={hoverIdx === null || hoverIdx === i ? 1 : 0.35} />
                <rect x={bar.peX} y={bar.peY} width={bar.barWidth} height={bar.peH}
                      fill="#fb7185" opacity={hoverIdx === null || hoverIdx === i ? 1 : 0.35} />
                {/* invisible full-height hit area -- easier to hover than the thin bars alone */}
                <rect x={bar.centerX - layout.slotWidth / 2} y={0} width={layout.slotWidth} height={HEIGHT} fill="transparent" />
              </g>
            );
          })}
          {pcrLine && (
            <path d={pcrLine.path} fill="none" stroke="#fbbf24" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity={0.85} />
          )}
        </svg>

        {hovered && (
          <div className="absolute top-2 left-2 bg-slate-800 border border-slate-700 rounded-lg p-3 text-xs shadow-xl pointer-events-none min-w-[190px]">
            <p className="text-white font-bold mb-1.5">
              Strike ₹{hovered.bar.strike}
              {hovered.bar.strike === atmStrike && <span className="ml-1.5 text-[9px] bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded">ATM</span>}
            </p>
            <div className="grid grid-cols-2 gap-x-3 gap-y-1">
              <span className="text-emerald-400">CE OI</span><span className="text-right text-slate-200">{fmtLots(hovered.ce.oi)}</span>
              <span className="text-emerald-400">CE LTP</span><span className="text-right text-slate-200">₹{hovered.ce.ltp}</span>
              {hovered.ce.delta != null && (<><span className="text-emerald-400">CE Δ</span><span className="text-right text-slate-200">{hovered.ce.delta}</span></>)}
              <span className="text-rose-400">PE OI</span><span className="text-right text-slate-200">{fmtLots(hovered.pe.oi)}</span>
              <span className="text-rose-400">PE LTP</span><span className="text-right text-slate-200">₹{hovered.pe.ltp}</span>
              {hovered.pe.delta != null && (<><span className="text-rose-400">PE Δ</span><span className="text-right text-slate-200">{hovered.pe.delta}</span></>)}
              <span className="text-amber-400">PCR</span><span className="text-right text-slate-200">{hovered.pcr != null ? hovered.pcr.toFixed(2) : '—'}</span>
            </div>
          </div>
        )}
      </div>

      <p className="text-[10px] text-slate-600 mt-2">
        Bars sized to open interest (lots), tallest bar in view = highest OI. Hover a strike for OI, LTP, per-strike PCR, and Delta.
      </p>
    </div>
  );
}
