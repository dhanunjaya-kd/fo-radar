import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

const SEGMENT_COLOR = { Advances: '#34d399', Declines: '#fb7185', Unchanged: '#64748b' };

// Aug 28 2026: geometry verified in test_donut_geometry.js before this
// was written -- full-circle sweep sums to exactly 360deg, zero-gap
// segments, zero-value segments correctly omitted rather than drawn
// as degenerate arcs. Same stroked-polyline technique as the
// Sentiment gauge (MarketSentimentGauge.jsx) -- sidesteps SVG's arc
// command sweep-flag ambiguity entirely by using only straight-line
// segments between explicitly computed points.
function pointOnArc(cx, cy, r, angleDeg) {
  const angleRad = (angleDeg * Math.PI) / 180;
  return { x: cx + r * Math.cos(angleRad), y: cy - r * Math.sin(angleRad) };
}

function arcPolylinePath(cx, cy, r, startAngle, endAngle, segments = 40) {
  const pts = [];
  for (let i = 0; i <= segments; i++) {
    const angle = startAngle + (endAngle - startAngle) * (i / segments);
    pts.push(pointOnArc(cx, cy, r, angle));
  }
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(' ');
}

function computeDonutSegments(advances, declines, unchanged) {
  const total = advances + declines + unchanged;
  if (total === 0) return [];
  const segments = [
    { label: 'Advances', value: advances },
    { label: 'Declines', value: declines },
    { label: 'Unchanged', value: unchanged },
  ];
  let currentAngle = 90;
  const result = [];
  for (const seg of segments) {
    if (seg.value === 0) continue;
    const sweepDeg = (seg.value / total) * 360;
    const endAngle = currentAngle - sweepDeg;
    result.push({ label: seg.label, value: seg.value, startAngle: currentAngle, endAngle, pct: (seg.value / total) * 100 });
    currentAngle = endAngle;
  }
  return result;
}

export default function AdvanceDeclineDonut() {
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
        console.error('Advance/decline donut fetch error:', err);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (loading) {
    return <div className="h-40 w-40 mx-auto rounded-full bg-slate-900/30 animate-pulse" />;
  }
  if (!breadth || breadth.total === 0) {
    return <p className="text-xs text-slate-500 text-center py-4">No breadth data yet.</p>;
  }

  const cx = 100, cy = 100, r = 70;
  const segments = computeDonutSegments(breadth.advances, breadth.declines, breadth.unchanged);

  return (
    <div className="flex items-center gap-4">
      <svg width="140" height="140" viewBox="0 0 200 200" className="shrink-0">
        {segments.map(seg => (
          <path
            key={seg.label}
            d={arcPolylinePath(cx, cy, r, seg.startAngle, seg.endAngle)}
            fill="none"
            stroke={SEGMENT_COLOR[seg.label]}
            strokeWidth="24"
            strokeLinecap="butt"
          />
        ))}
        <text x={cx} y={cy - 6} textAnchor="middle" fill="#f1f5f9" style={{ fontSize: '28px', fontWeight: 'bold' }}>
          {breadth.total}
        </text>
        <text x={cx} y={cy + 16} textAnchor="middle" fill="#64748b" style={{ fontSize: '11px' }}>
          F&O stocks
        </text>
      </svg>
      <div className="space-y-1.5">
        {segments.map(seg => (
          <div key={seg.label} className="flex items-center gap-2 text-xs">
            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: SEGMENT_COLOR[seg.label] }} />
            <span className="text-slate-400 w-20">{seg.label}</span>
            <span className="text-white font-medium tabular-nums">{seg.value}</span>
            <span className="text-slate-500 text-[10px]">({seg.pct.toFixed(1)}%)</span>
          </div>
        ))}
      </div>
    </div>
  );
}
