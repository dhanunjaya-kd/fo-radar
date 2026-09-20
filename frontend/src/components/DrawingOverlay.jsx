import { useRef, useState } from 'react';

// Sep 19 2026: scoped to the two most commonly used drawing tools
// (trendline, horizontal line) rather than attempting the reference's
// full toolbox (Fibonacci, angle, curve, etc.) -- each additional
// tool is its own real piece of work, not a one-line addition to this
// one. Real, stated limitation: these are SCREEN-SPACE (pixel)
// coordinates captured on click, not anchored to the chart's actual
// price/time scale the way a proper drawing tool would be -- recharts
// doesn't expose its internal scale functions to an external overlay
// without much deeper integration than this pass covers. Practical
// effect: switching interval or range redraws the chart at a
// different scale, so old drawings would land in the wrong place if
// kept -- they're cleared on any symbol/interval/range change instead
// of silently drifting out of position.
export default function DrawingOverlay({ tool, drawings, setDrawings }) {
  const [pending, setPending] = useState(null);
  const ref = useRef(null);

  const handleClick = (e) => {
    if (!tool || tool === 'none') return;
    const rect = ref.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    if (tool === 'horizontal') {
      setDrawings((d) => [...d, { type: 'horizontal', y }]);
    } else if (tool === 'trendline') {
      if (!pending) {
        setPending({ x, y });
      } else {
        setDrawings((d) => [...d, { type: 'trendline', x1: pending.x, y1: pending.y, x2: x, y2: y }]);
        setPending(null);
      }
    }
  };

  const active = tool && tool !== 'none';

  return (
    <svg
      ref={ref}
      className="absolute inset-0 w-full h-full"
      style={{ pointerEvents: active ? 'auto' : 'none', cursor: active ? 'crosshair' : 'default' }}
      onClick={handleClick}
    >
      {drawings.map((d, i) =>
        d.type === 'horizontal' ? (
          <g key={i}>
            <line x1={0} y1={d.y} x2="100%" y2={d.y} stroke="#facc15" strokeWidth={1.5} />
          </g>
        ) : (
          <line key={i} x1={d.x1} y1={d.y1} x2={d.x2} y2={d.y2} stroke="#facc15" strokeWidth={1.5} />
        )
      )}
      {pending && <circle cx={pending.x} cy={pending.y} r={3} fill="#facc15" />}
    </svg>
  );
}
