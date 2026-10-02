import { useEffect, useRef, useState } from 'react';

// Oct 2 2026: mini candlestick chart for a Scanner card -- plain SVG on
// purpose (no chart library): a scanner grid shows hundreds of these, and
// a lightweight-charts instance per card would be far too heavy. Candles
// only draw once the card scrolls into view (IntersectionObserver) and
// stay drawn afterwards. `onVisibility(symbol, inView)` tells the Scanner
// which cards are on screen so it can fetch missing history for exactly
// those (see /api/scanner/candles/); `status` is 'loading' | 'unavailable'.
//
// `candles` is [[open, high, low, close], ...] oldest -> newest (the last
// one is today's still-forming candle). `setup` is the backend's
// scanner_levels.range_setup() result: a 20-day range plus, when the card
// has a clear lean, breakout / target / stop. Nothing here computes a
// level -- it only draws what the backend sent.

const UP = '#34d399';
const DOWN = '#f87171';
const BREAKOUT = '#f59e0b';
const W = 300, H = 132, PAD_T = 14, PAD_B = 8, PAD_L = 4, AXIS_W = 58;

const fmt = (v) => (v >= 1000 ? Math.round(v).toLocaleString('en-IN') : v.toFixed(1));

export default function ScannerMiniChart({ symbol, candles, setup, status, onVisibility }) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);
  const cb = useRef(onVisibility);
  cb.current = onVisibility;

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      if (cb.current) cb.current(symbol, true);
      return undefined;
    }
    const io = new IntersectionObserver((entries) => {
      const inView = entries.some((e) => e.isIntersecting);
      if (inView) setVisible(true);
      if (cb.current) cb.current(symbol, inView);
    }, { rootMargin: '150px' });
    io.observe(el);
    return () => { io.disconnect(); if (cb.current) cb.current(symbol, false); };
  }, [symbol]);

  if (!candles || candles.length < 5) {
    return (
      <div ref={ref} className="aspect-[300/132] w-full rounded-lg bg-slate-950/50 border border-slate-800 flex items-center justify-center text-[10px] text-slate-600">
        {status === 'unavailable' ? 'no daily history available' : (
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full border border-slate-600 border-t-slate-300 animate-spin" />
            loading chart…
          </span>
        )}
      </div>
    );
  }

  let body = null;
  if (visible) {
    const levels = [];
    if (setup?.breakout != null) levels.push({ key: 'breakout', v: setup.breakout, color: BREAKOUT });
    if (setup?.target != null) levels.push({ key: 'target', v: setup.target, color: UP });
    if (setup?.stop != null) levels.push({ key: 'stop', v: setup.stop, color: DOWN });

    const lo = Math.min(...candles.map((c) => c[2]));
    const hi = Math.max(...candles.map((c) => c[1]));
    const span = hi - lo || 1;
    // A measured-move target can sit far above the candles; let levels stretch the
    // scale only up to 80% of the candle span so they never flatten the candles.
    const yMin = Math.min(lo, ...levels.map((l) => l.v).filter((v) => v >= lo - span * 0.8));
    const yMax = Math.max(hi, ...levels.map((l) => l.v).filter((v) => v <= hi + span * 0.8));
    const range = yMax - yMin || 1;
    const plotW = W - AXIS_W - PAD_L;
    const y = (v) => PAD_T + (1 - (Math.min(yMax, Math.max(yMin, v)) - yMin) / range) * (H - PAD_T - PAD_B);
    const step = plotW / candles.length;
    const bw = Math.max(1.2, step * 0.62);
    const x = (i) => PAD_L + step * i + step / 2;

    const lb = setup?.lookback || 0;
    const boxX = lb ? x(candles.length - 1 - lb) - step / 2 : null;

    // keep right-edge tags from overlapping: nudge each down until it clears the previous
    const tags = levels.map((l) => ({ ...l, ty: y(l.v) })).sort((a, b) => a.ty - b.ty);
    for (let i = 1; i < tags.length; i += 1) if (tags[i].ty - tags[i - 1].ty < 12) tags[i].ty = tags[i - 1].ty + 12;

    body = (
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full block" role="img" aria-label="Daily candles with range and levels">
        {setup?.range_high != null && boxX != null && (
          <rect x={boxX} y={y(setup.range_high)} width={W - AXIS_W - boxX} height={Math.max(1, y(setup.range_low) - y(setup.range_high))}
                fill="#38bdf8" opacity="0.06" stroke="#38bdf8" strokeOpacity="0.25" strokeDasharray="2 3" />
        )}
        {candles.map((c, i) => {
          const [o, h, l, cl] = c;
          const color = cl >= o ? UP : DOWN;
          const top = y(Math.max(o, cl)), bot = y(Math.min(o, cl));
          return (
            <g key={i}>
              <line x1={x(i)} x2={x(i)} y1={y(h)} y2={y(l)} stroke={color} strokeWidth="1" />
              <rect x={x(i) - bw / 2} y={top} width={bw} height={Math.max(1, bot - top)} fill={color} />
            </g>
          );
        })}
        {levels.map((l) => (
          <line key={l.key} x1={PAD_L} x2={W - AXIS_W} y1={y(l.v)} y2={y(l.v)} stroke={l.color} strokeWidth="1" strokeDasharray="4 3" opacity="0.85" />
        ))}
        {tags.map((l) => (
          <g key={`t-${l.key}`}>
            <rect x={W - AXIS_W + 2} y={l.ty - 6} width={AXIS_W - 4} height={12} rx="2" fill={l.color} />
            <text x={W - AXIS_W / 2} y={l.ty + 3} textAnchor="middle" fontSize="8.5" fontWeight="700" fill="#0b1220">₹{fmt(l.v)}</text>
          </g>
        ))}
      </svg>
    );
  }

  return (
    <div ref={ref} className="relative aspect-[300/132] w-full rounded-lg bg-slate-950/50 border border-slate-800 overflow-hidden">
      <span className="absolute top-1 left-1.5 z-10 text-[9px] font-semibold text-slate-400 bg-slate-800/80 border border-slate-700 rounded px-1">1D</span>
      {body}
    </div>
  );
}
