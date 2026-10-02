// Oct 2 2026: draws one detected chart pattern -- candles, the pattern's own fitted lines
// (trendlines / neckline / curve), labelled pivots, and trigger / target / stop tags.
// Plain SVG, no chart library: the Chart Patterns tab shows dozens of these at once.
// Nothing here computes geometry; it draws exactly what backend chart_patterns.py fitted.

const UP = '#34d399';
const DOWN = '#f87171';
const LINE = '#f0b27a';          // pattern lines (trendlines, neckline, curve) -- warm tan like the reference
const TRIGGER = '#f59e0b';
const TARGET = '#34d399';
const STOP = '#f87171';

const fmt = (v) => (v == null ? '' : v >= 1000 ? Math.round(v).toLocaleString('en-IN') : v >= 100 ? v.toFixed(1) : v.toFixed(2));

export default function PatternChart({ pattern, large = false }) {
  const { candles, lines = [], markers = [], curve, trigger, stop, target, direction } = pattern;
  if (!candles || candles.length < 3) return null;

  const W = large ? 560 : 300;
  const H = large ? 300 : 132;
  const AXIS = large ? 74 : 56;
  const PAD_T = large ? 22 : 14;
  const PAD_B = large ? 24 : 8;
  const PAD_L = 4;
  const fs = large ? 11 : 8.5;      // tag font
  const tagH = large ? 16 : 12;

  const levels = [];
  if (trigger != null) levels.push({ key: 'trigger', v: trigger, color: TRIGGER });
  if (target != null) levels.push({ key: 'target', v: target, color: TARGET });
  if (stop != null) levels.push({ key: 'stop', v: stop, color: STOP });

  const lo = Math.min(...candles.map((c) => c[2]));
  const hi = Math.max(...candles.map((c) => c[1]));
  const span = hi - lo || 1;
  const near = (v) => v >= lo - span * 0.7 && v <= hi + span * 0.7;
  const geom = [
    ...lines.flatMap((l) => [l.y1, l.y2]),
    ...markers.map((m) => m.y),
    ...(curve || []).map((p) => p.y),
    ...levels.map((l) => l.v),
  ].filter(near);
  const yMin = Math.min(lo, ...geom);
  const yMax = Math.max(hi, ...geom);
  const range = yMax - yMin || 1;

  const n = candles.length;
  const plotW = W - AXIS - PAD_L;
  const step = plotW / n;
  const bw = Math.max(1.2, step * 0.62);
  const x = (i) => PAD_L + step * i + step / 2;
  const y = (v) => PAD_T + (1 - (Math.min(yMax, Math.max(yMin, v)) - yMin) / range) * (H - PAD_T - PAD_B);

  // right-edge tags: keep them from overlapping
  const tags = levels.map((l) => ({ ...l, ty: y(l.v) })).sort((a, b) => a.ty - b.ty);
  for (let i = 1; i < tags.length; i += 1) if (tags[i].ty - tags[i - 1].ty < tagH) tags[i].ty = tags[i - 1].ty + tagH;

  const bear = direction === 'Bearish';
  const lineStyle = (kind) => {
    if (kind === 'trigger') return { stroke: TRIGGER, dash: '5 3', w: 1.2 };
    if (kind === 'resistance' || kind === 'support') return { stroke: '#94a3b8', dash: '3 3', w: 1 };
    if (kind === 'pole') return { stroke: LINE, dash: '2 3', w: 1.2 };
    return { stroke: LINE, dash: null, w: large ? 1.8 : 1.4 };
  };

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full block" role="img" aria-label={`${pattern.name} on daily candles`}>
      {large && [0.25, 0.5, 0.75].map((f) => (
        <line key={f} x1={PAD_L} x2={W - AXIS} y1={PAD_T + f * (H - PAD_T - PAD_B)} y2={PAD_T + f * (H - PAD_T - PAD_B)} stroke="#1e293b" strokeWidth="1" />
      ))}
      {candles.map((c, i) => {
        const [o, h, l, cl] = c;
        const color = cl >= o ? UP : DOWN;
        const top = y(Math.max(o, cl)), bot = y(Math.min(o, cl));
        return (
          <g key={i}>
            <line x1={x(i)} x2={x(i)} y1={y(h)} y2={y(l)} stroke={color} strokeWidth={large ? 1.3 : 1} />
            <rect x={x(i) - bw / 2} y={top} width={bw} height={Math.max(1, bot - top)} fill={color} />
          </g>
        );
      })}
      {levels.map((l) => (
        <line key={l.key} x1={PAD_L} x2={W - AXIS} y1={y(l.v)} y2={y(l.v)} stroke={l.color} strokeWidth="1" strokeDasharray="4 3" opacity="0.7" />
      ))}
      {curve && curve.length > 1 && (
        <polyline fill="none" stroke={LINE} strokeWidth={large ? 1.8 : 1.4} points={curve.map((p) => `${x(p.x)},${y(p.y)}`).join(' ')} />
      )}
      {lines.map((l, i) => {
        const st = lineStyle(l.kind);
        return <line key={i} x1={x(l.x1)} y1={y(l.y1)} x2={x(Math.min(l.x2, n - 1))} y2={y(l.y2)} stroke={st.stroke} strokeWidth={st.w} strokeDasharray={st.dash || undefined} />;
      })}
      {markers.map((m, i) => (
        <g key={i}>
          <circle cx={x(m.x)} cy={y(m.y)} r={large ? 3.4 : 2.4} fill="#0f172a" stroke={LINE} strokeWidth="1.4" />
          {m.label && (
            <text x={x(m.x)} y={y(m.y) + (bear ? -(large ? 8 : 6) : (large ? 15 : 11))} textAnchor="middle" fontSize={large ? 10 : 7.5} fill="#cbd5e1" fontWeight="600">{m.label}</text>
          )}
        </g>
      ))}
      {tags.map((l) => (
        <g key={`t-${l.key}`}>
          <rect x={W - AXIS + 2} y={l.ty - tagH / 2} width={AXIS - 4} height={tagH} rx="2" fill={l.color} />
          <text x={W - AXIS / 2} y={l.ty + fs / 3} textAnchor="middle" fontSize={fs} fontWeight="700" fill="#0b1220">₹{fmt(l.v)}</text>
        </g>
      ))}
      {large && pattern.window_start && (
        <>
          <text x={PAD_L + 2} y={H - 6} fontSize="10" fill="#64748b">{pattern.window_start}</text>
          <text x={W - AXIS - 2} y={H - 6} fontSize="10" fill="#64748b" textAnchor="end">{pattern.data_through}</text>
        </>
      )}
    </svg>
  );
}
