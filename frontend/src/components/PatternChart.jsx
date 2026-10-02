// Oct 2 2026: draws one detected chart pattern -- candles, the pattern's own fitted lines
// (trendlines / neckline / curve), numbered touches, labelled pivots, the break, and
// trigger / target / stop tags. Plain SVG, no chart library: the Chart Patterns tab shows
// dozens of these at once. Nothing here computes geometry; it draws exactly what backend
// chart_patterns.py fitted. `large` adds the volume strip, span bracket, dates and target zone.

import { useTheme } from './ThemeContext';

export const COLORS = {
  up: '#34d399',
  down: '#f87171',
  resistance: '#fb923c',   // upper trendline
  support: '#34d399',      // lower trendline
  line: '#f0b27a',         // necklines, curves, poles
  trigger: '#f59e0b',
  target: '#34d399',
  stop: '#f87171',
};

const COLORS_LIGHT = {
  up: '#059669', down: '#e11d48', resistance: '#ea580c', support: '#059669', line: '#c2410c',
  trigger: '#d97706', target: '#059669', stop: '#e11d48',
};
export const paletteFor = (light) => (light ? COLORS_LIGHT : COLORS);
// chart chrome that is neither a pattern line nor a candle
const chromeFor = (light) => (light
  ? { grid: '#eceff3', disc: '#ffffff', discInk: '#111827', numberFill: '#ffffff', tagInk: '#ffffff', muted: '#6b7280', bracket: '#9ca3af', bracketInk: '#374151', badge: '#ffffff', level: '#9ca3af' }
  : { grid: '#1e293b', disc: '#0f172a', discInk: '#0f172a', numberFill: '#f8fafc', tagInk: '#0b1220', muted: '#64748b', bracket: '#94a3b8', bracketInk: '#cbd5e1', badge: '#1f1411', level: '#94a3b8' });

const fmt = (v) => (v == null ? '' : v >= 1000 ? Math.round(v).toLocaleString('en-IN') : v >= 100 ? v.toFixed(1) : v.toFixed(2));

// What each drawn line kind is called in the legend
export function legendFor(pattern, light = false) {
  const COLORS = paletteFor(light);
  const items = [];
  const t = pattern.touches || {};
  const kinds = new Set((pattern.lines || []).map((l) => l.kind));
  if (kinds.has('upper')) items.push({ color: COLORS.resistance, label: `Resistance${t.upper ? ` · ${t.upper} touches` : ''}` });
  if (kinds.has('lower')) items.push({ color: COLORS.support, label: `Support${t.lower ? ` · ${t.lower} touches` : ''}` });
  if (kinds.has('pole')) items.push({ color: COLORS.line, label: 'Pole', dash: '2 3' });
  if (pattern.curve) items.push({ color: COLORS.line, label: 'Rounded shape' });
  if (kinds.has('trigger') && pattern.trigger != null) items.push({ color: COLORS.trigger, label: 'Neckline / rim', dash: '5 3' });
  if (kinds.has('resistance')) items.push({ color: light ? '#9ca3af' : '#94a3b8', label: 'Tops level', dash: '3 3' });
  if (pattern.trigger != null) items.push({ color: COLORS.trigger, label: pattern.direction === 'Bearish' ? 'Breakdown trigger' : 'Breakout trigger', dash: '5 3' });
  if (pattern.target != null) items.push({ color: COLORS.target, label: 'Target', dash: '4 3' });
  if (pattern.stop != null) items.push({ color: COLORS.stop, label: 'Stop', dash: '4 3' });
  return items;
}

export default function PatternChart({ pattern, large = false }) {
  const light = useTheme().theme === 'light';
  const COLORS = paletteFor(light);
  const X = chromeFor(light);
  const { candles, lines = [], markers = [], curve, trigger, stop, target, direction, volumes } = pattern;
  if (!candles || candles.length < 3) return null;

  const n = candles.length;
  const W = large ? 600 : 300;
  const H = large ? 330 : 132;
  const AXIS = large ? 78 : 56;
  const PAD_T = large ? 36 : 14;
  const volH = large && volumes ? 38 : 0;
  const PAD_B = (large ? 20 : 8) + volH;
  const PAD_L = 4;
  const fs = large ? 11 : 8.5;
  const tagH = large ? 17 : 12;

  const levels = [];
  if (trigger != null) levels.push({ key: 'trigger', v: trigger, color: COLORS.trigger });
  if (target != null) levels.push({ key: 'target', v: target, color: COLORS.target });
  if (stop != null) levels.push({ key: 'stop', v: stop, color: COLORS.stop });

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

  const plotW = W - AXIS - PAD_L;
  const step = plotW / n;
  const bw = Math.max(1.2, step * 0.62);
  const x = (i) => PAD_L + step * i + step / 2;
  const plotBottom = H - PAD_B;
  const y = (v) => PAD_T + (1 - (Math.min(yMax, Math.max(yMin, v)) - yMin) / range) * (plotBottom - PAD_T);

  const tags = levels.map((l) => ({ ...l, ty: y(l.v) })).sort((a, b) => a.ty - b.ty);
  for (let i = 1; i < tags.length; i += 1) if (tags[i].ty - tags[i - 1].ty < tagH) tags[i].ty = tags[i - 1].ty + tagH;

  const bear = direction === 'Bearish';
  const lineStyle = (kind) => {
    if (kind === 'upper') return { stroke: COLORS.resistance, dash: null, w: large ? 2 : 1.5 };
    if (kind === 'lower') return { stroke: COLORS.support, dash: null, w: large ? 2 : 1.5 };
    if (kind === 'trigger') return { stroke: COLORS.trigger, dash: '5 3', w: 1.2 };
    if (kind === 'resistance' || kind === 'support') return { stroke: X.level, dash: '3 3', w: 1 };
    if (kind === 'pole') return { stroke: COLORS.line, dash: '2 3', w: 1.2 };
    return { stroke: COLORS.line, dash: null, w: large ? 1.8 : 1.4 };
  };

  const maxVol = volumes ? Math.max(...volumes) || 1 : 1;
  const startX = pattern.start_x != null ? Math.max(0, pattern.start_x) : null;
  const endX = pattern.end_x != null ? Math.min(n - 1, pattern.end_x) : null;
  const brokeX = pattern.broke_x != null && pattern.broke_x >= 0 ? pattern.broke_x : null;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full block" role="img" aria-label={`${pattern.name} on daily candles`}>
      {large && [0.25, 0.5, 0.75].map((f) => (
        <line key={f} x1={PAD_L} x2={W - AXIS} y1={PAD_T + f * (plotBottom - PAD_T)} y2={PAD_T + f * (plotBottom - PAD_T)} stroke={X.grid} strokeWidth="1" />
      ))}

      {/* target zone: from the break (or pattern end) out to the target */}
      {large && trigger != null && target != null && (
        <rect x={x(brokeX ?? endX ?? n - 1)} y={Math.min(y(trigger), y(target))} width={Math.max(2, W - AXIS - x(brokeX ?? endX ?? n - 1))}
              height={Math.abs(y(target) - y(trigger))} fill={COLORS.target} opacity="0.07" />
      )}

      {/* volume strip */}
      {large && volumes && volumes.map((vv, i) => (
        <rect key={`v${i}`} x={x(i) - bw / 2} y={H - 20 - (vv / maxVol) * (volH - 4)} width={bw} height={(vv / maxVol) * (volH - 4)}
              fill={candles[i][3] >= candles[i][0] ? COLORS.up : COLORS.down} opacity="0.35" />
      ))}

      {candles.map((c, i) => {
        const [o, h, l, cl] = c;
        const color = cl >= o ? COLORS.up : COLORS.down;
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
        <polyline fill="none" stroke={COLORS.line} strokeWidth={large ? 1.8 : 1.4} points={curve.map((p) => `${x(p.x)},${y(p.y)}`).join(' ')} />
      )}
      {lines.map((l, i) => {
        const st = lineStyle(l.kind);
        return <line key={i} x1={x(l.x1)} y1={y(l.y1)} x2={x(Math.min(l.x2, n - 1))} y2={y(l.y2)} stroke={st.stroke} strokeWidth={st.w} strokeDasharray={st.dash || undefined} />;
      })}

      {/* pivots: numbered touches get a numbered disc, named pivots keep their text label */}
      {markers.map((m, i) => {
        const numeric = /^\d+$/.test(m.label || '');
        const upper = m.side ? m.side === 'upper' : bear;
        const color = numeric ? (upper ? COLORS.resistance : COLORS.support) : COLORS.line;
        const r = large ? 3.4 : 2.4;
        if (numeric && large) {
          const cy = y(m.y) + (upper ? -14 : 14);
          return (
            <g key={i}>
              <circle cx={x(m.x)} cy={y(m.y)} r={r} fill={X.disc} stroke={color} strokeWidth="1.6" />
              <circle cx={x(m.x)} cy={cy} r="7" fill={X.numberFill} stroke={color} strokeWidth="1.4" />
              <text x={x(m.x)} y={cy + 3.4} textAnchor="middle" fontSize="9.5" fontWeight="700" fill={X.discInk}>{m.label}</text>
            </g>
          );
        }
        return (
          <g key={i}>
            <circle cx={x(m.x)} cy={y(m.y)} r={r} fill={X.disc} stroke={color} strokeWidth="1.4" />
            {m.label && !numeric && (
              <text x={x(m.x)} y={y(m.y) + (upper ? -(large ? 8 : 6) : (large ? 15 : 11))} textAnchor="middle" fontSize={large ? 10 : 7.5} fill={X.bracketInk} fontWeight="600">{m.label}</text>
            )}
          </g>
        );
      })}

      {/* the break itself */}
      {large && brokeX != null && (
        <g>
          <circle cx={x(brokeX)} cy={y(candles[brokeX][3])} r="3.4" fill={X.numberFill} stroke={bear ? COLORS.stop : COLORS.up} strokeWidth="1.6" />
          <rect x={x(brokeX) - 28} y={y(Math.max(candles[brokeX][1], candles[brokeX][3])) - 24} width="56" height="15" rx="7.5" fill={X.badge} stroke={bear ? COLORS.stop : COLORS.up} strokeWidth="1" />
          <text x={x(brokeX)} y={y(Math.max(candles[brokeX][1], candles[brokeX][3])) - 13.5} textAnchor="middle" fontSize="9" fontWeight="700" fill={bear ? (light ? '#be123c' : '#fca5a5') : (light ? '#047857' : '#86efac')}>{bear ? 'Breakdown' : 'Breakout'}</text>
          <text x={x(brokeX)} y={y(Math.max(candles[brokeX][1], candles[brokeX][3])) - 4} textAnchor="middle" fontSize="8" fill={bear ? COLORS.stop : COLORS.up}>{bear ? '▼' : '▲'}</text>
        </g>
      )}

      {/* span bracket */}
      {large && startX != null && endX != null && endX > startX && (
        <g>
          <path d={`M ${x(startX)} 24 L ${x(startX)} 18 L ${x(endX)} 18 L ${x(endX)} 24`} fill="none" stroke={X.bracket} strokeWidth="1" />
          <text x={(x(startX) + x(endX)) / 2} y="13" textAnchor="middle" fontSize="10.5" fontWeight="600" fill={X.bracketInk}>{pattern.span_bars} daily candles</text>
        </g>
      )}

      {tags.map((l) => (
        <g key={`t-${l.key}`}>
          <rect x={W - AXIS + 2} y={l.ty - tagH / 2} width={AXIS - 4} height={tagH} rx="3" fill={l.color} />
          <text x={W - AXIS / 2} y={l.ty + fs / 3} textAnchor="middle" fontSize={fs} fontWeight="700" fill={X.tagInk}>₹{fmt(l.v)}</text>
        </g>
      ))}

      {large && pattern.window_start && (
        <>
          <text x={PAD_L + 2} y={H - 5} fontSize="10" fill={X.muted}>{pattern.window_start}</text>
          <text x={W - AXIS - 2} y={H - 5} fontSize="10" fill={X.muted} textAnchor="end">{pattern.data_through}</text>
        </>
      )}
    </svg>
  );
}
