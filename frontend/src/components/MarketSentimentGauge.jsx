import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

const BAND_COLORS = {
  'Very Bearish': '#ef4444', // red-500
  'Bearish': '#fb923c',      // orange-400
  'Neutral': '#fbbf24',      // amber-400
  'Bullish': '#a3e635',      // lime-400
  'Very Bullish': '#34d399', // emerald-400
};
// Left-to-right gauge order, matching angle 180deg (left) -> 0deg (right).
const BAND_ORDER = ['Very Bearish', 'Bearish', 'Neutral', 'Bullish', 'Very Bullish'];

// Aug 28 2026: coordinate math verified in test_gauge_geometry.js
// before this component was ever written -- left/top/right needle
// positions, 5 bands of exactly 36deg each spanning the full 180deg
// with no gaps, and a real computed score landing in the correct
// visual band. Bands are drawn as STROKED POLYLINES (many small line
// segments along the angle range), not SVG arc commands -- sidesteps
// the arc command's sweep-flag ambiguity entirely (which direction a
// true <path> arc bulges can't be verified visually in this
// environment) by using only straight lines between explicitly
// computed, already-tested points. Correct by construction, not by
// guessing a sweep-flag value.
function pointOnArc(cx, cy, r, angleDeg) {
  const angleRad = (angleDeg * Math.PI) / 180;
  return { x: cx + r * Math.cos(angleRad), y: cy - r * Math.sin(angleRad) };
}

function scoreToAngle(score) {
  const clamped = Math.max(0, Math.min(100, score));
  return 180 - (clamped / 100) * 180;
}

function arcPolylinePath(cx, cy, r, startAngle, endAngle, segments = 20) {
  const pts = [];
  for (let i = 0; i <= segments; i++) {
    const angle = startAngle + (endAngle - startAngle) * (i / segments);
    pts.push(pointOnArc(cx, cy, r, angle));
  }
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(' ');
}

export default function MarketSentimentGauge() {
  const [sentiment, setSentiment] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/market-summary/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (mounted) setSentiment(json.sentiment || null);
      } catch (err) {
        console.error('Market sentiment fetch error:', err);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchData();
    // Same 30s cadence as the other market-summary-fed panels.
    const interval = setInterval(fetchData, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (loading || !sentiment) {
    return <div className="h-48 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/50" />;
  }

  const cx = 100, cy = 100, r = 80;
  const score = sentiment.score ?? 50;
  const needleAngle = scoreToAngle(score);
  const needleLen = r * 0.82; // stays inside the band ring's inner edge (r - half strokeWidth), no visual overlap
  const needleTip = pointOnArc(cx, cy, needleLen, needleAngle);

  // Each band is exactly 36deg (180/5), boundaries verified with no
  // gaps/overlaps in test_gauge_geometry.js.
  const bandAngleRanges = BAND_ORDER.map((_, i) => [180 - i * 36, 180 - (i + 1) * 36]);

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
      <h3 className="text-sm font-bold text-white mb-2">Market Sentiment</h3>
      <div className="flex items-center gap-4 flex-wrap">
        <svg width="200" height="115" viewBox="0 0 200 115" className="shrink-0">
          {BAND_ORDER.map((label, i) => (
            <path
              key={label}
              d={arcPolylinePath(cx, cy, r, bandAngleRanges[i][0], bandAngleRanges[i][1])}
              fill="none"
              stroke={BAND_COLORS[label]}
              strokeWidth="14"
              strokeLinecap="butt"
            />
          ))}
          <line x1={cx} y1={cy} x2={needleTip.x} y2={needleTip.y} stroke="#e2e8f0" strokeWidth="3" strokeLinecap="round" />
          <circle cx={cx} cy={cy} r="5" fill="#e2e8f0" />
          <text x={cx} y={cy + 24} textAnchor="middle" fill="#f1f5f9" style={{ fontSize: '22px', fontWeight: 'bold' }}>
            {Math.round(score)}
          </text>
        </svg>
        <div className="flex-1 space-y-1.5 min-w-[140px]">
          {[...BAND_ORDER].reverse().map((label) => {
            const band = sentiment.bands.find(b => b.label === label);
            return (
              <div key={label} className="flex items-center gap-2 text-[11px]">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: BAND_COLORS[label] }} />
                <span className="text-slate-400 flex-1">{label}</span>
                <span className="text-white font-medium tabular-nums">{band ? band.pct : 0}%</span>
              </div>
            );
          })}
        </div>
      </div>
      <p className="text-center text-xs font-semibold mt-1" style={{ color: BAND_COLORS[sentiment.label] }}>
        {sentiment.label}
      </p>
      <p className="text-[10px] text-slate-500 text-center mt-1">
        Real-time distribution across your {sentiment.bands.reduce((sum, b) => sum + b.count, 0)}-stock F&O universe
      </p>
    </div>
  );
}
