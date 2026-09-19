import { useState, useEffect } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

/**
 * Sep 18 2026: one Dashboard index card (NIFTY/BANKNIFTY/SENSEX/VIX).
 * Every value shown -- price, change%, sparkline points, 18-day
 * range, regime label -- comes directly from /api/index-card/<name>/,
 * itself backed by get_index_card_data() in index_tracker.py. This
 * component only lays those numbers out; it computes no market data
 * of its own beyond pure SVG coordinate geometry (mapping a price
 * onto a pixel position), the same kind of math MarketSentimentGauge
 * already uses for its own arc.
 */

function formatSparklineDate(dateStr) {
  // dateStr is "YYYY-MM-DD" from the backend's own real candle date
  // (index_tracker.py's _fetch_daily_history), not estimated from
  // position in the array.
  if (!dateStr) return '';
  const d = new Date(dateStr + 'T00:00:00');
  if (isNaN(d.getTime())) return '';
  return new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short' }).format(d);
}

function Sparkline({ values, dates, positive }) {
  const [hoverIdx, setHoverIdx] = useState(null);
  if (!values || values.length < 2) return <div className="h-16" />;
  const w = 280, h = 64, pad = 2;
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const coords = values.map((v, i) => ({
    x: pad + (i / (values.length - 1)) * (w - pad * 2),
    y: pad + (1 - (v - min) / range) * (h - pad * 2),
  }));
  const points = coords.map(c => `${c.x},${c.y}`);
  const color = positive ? '#34d399' : '#ef4444';
  const fillPoints = `${pad},${h} ${points.join(' ')} ${w - pad},${h}`;

  // Sep 19 2026: hover-to-see-price-and-date, matching the reference
  // dashboard's own chart-hover behavior. Nearest point by x-distance
  // (not exact pixel match) so the whole chart width is "live", not
  // just the exact pixel of each of the 18 data points.
  const handleMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = ((e.clientX - rect.left) / rect.width) * w;
    let nearest = 0, bestDist = Infinity;
    coords.forEach((c, i) => {
      const dist = Math.abs(c.x - relX);
      if (dist < bestDist) { bestDist = dist; nearest = i; }
    });
    setHoverIdx(nearest);
  };

  const hover = hoverIdx != null ? { ...coords[hoverIdx], value: values[hoverIdx], date: dates && dates[hoverIdx] } : null;
  // Keep the label inside the chart's own width regardless of which
  // point is hovered -- anchor left/middle/right depending on
  // position instead of always centering, which would clip near
  // either edge.
  const labelAnchor = hover ? (hover.x < 50 ? 'start' : hover.x > w - 50 ? 'end' : 'middle') : 'middle';
  const labelX = hover ? (labelAnchor === 'start' ? 0 : labelAnchor === 'end' ? w : hover.x) : 0;

  return (
    <svg
      width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none"
      onMouseMove={handleMove}
      onMouseLeave={() => setHoverIdx(null)}
      style={{ cursor: hover ? 'crosshair' : 'default' }}
    >
      <polygon points={fillPoints} fill={color} opacity="0.12" />
      <polyline points={points.join(' ')} fill="none" stroke={color} strokeWidth="1.5" />
      {hover && (
        <>
          <line x1={hover.x} y1={0} x2={hover.x} y2={h} stroke="#94a3b8" strokeWidth="1" strokeDasharray="2,2" opacity="0.6" />
          <circle cx={hover.x} cy={hover.y} r="2.5" fill="#fff" stroke={color} strokeWidth="1.5" />
          <text
            x={labelX} y={hover.y > h / 2 ? 10 : h - 6}
            textAnchor={labelAnchor} fontSize="9" fontWeight="700"
            style={{ fill: 'var(--sparkline-label-fill)', paintOrder: 'stroke', stroke: 'var(--sparkline-label-halo)', strokeWidth: 3 }}
          >
            {hover.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            {hover.date ? ` · ${formatSparklineDate(hover.date)}` : ''}
          </text>
        </>
      )}
    </svg>
  );
}

function RangeBar({ low, high, current }) {
  if (low == null || high == null || current == null || high === low) return null;
  const pct = Math.max(0, Math.min(100, ((current - low) / (high - low)) * 100));
  return (
    <div>
      <div className="flex justify-between text-[10px] text-slate-500 mb-1">
        <span>18D {low.toLocaleString(undefined, { maximumFractionDigits: 1 })}</span>
        <span>{high.toLocaleString(undefined, { maximumFractionDigits: 1 })}</span>
      </div>
      <div className="relative w-full h-1 bg-slate-700 rounded-full">
        <div className="absolute top-1/2 -translate-y-1/2 w-2 h-2 rounded-full bg-white border-2 border-slate-900" style={{ left: `calc(${pct}% - 4px)` }} />
      </div>
    </div>
  );
}

const REGIME_COLORS = { Bullish: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/25', Bearish: 'text-rose-400 bg-rose-500/10 border-rose-500/25', Range: 'text-slate-400 bg-slate-500/10 border-slate-500/25' };
const VIX_BANDS = ['Calm', 'Normal', 'Elevated', 'High'];
const VIX_COLORS = ['#34d399', '#fbbf24', '#fb923c', '#ef4444'];

function VixGauge({ label }) {
  const idx = VIX_BANDS.indexOf(label);
  return (
    <div>
      <div className="flex h-1.5 rounded-full overflow-hidden mb-1">
        {VIX_COLORS.map((c, i) => <div key={i} className="flex-1" style={{ backgroundColor: c, opacity: i === idx ? 1 : 0.25 }} />)}
      </div>
      <div className="flex justify-between text-[9px] text-slate-500 uppercase">
        {VIX_BANDS.map(b => <span key={b} className={b === label ? 'text-white font-semibold' : ''}>{b}</span>)}
      </div>
    </div>
  );
}

export default function IndexCard({ indexName, displayName }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/index-card/${indexName}/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (!cancelled) { setData(json); setError(false); }
      } catch (err) {
        console.error(`IndexCard ${indexName} fetch error:`, err);
        if (!cancelled) setError(true);
      }
    };
    load();
    const interval = setInterval(load, 60000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [indexName]);

  if (error || !data) {
    return (
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 h-full flex items-center justify-center text-sm text-slate-500">
        {error ? `${displayName} unavailable` : 'Loading…'}
      </div>
    );
  }

  const positive = (data.change_percent || 0) >= 0;
  const isVix = data.regime_kind === 'vix_level';

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          <span className="text-xs font-semibold text-slate-300">{displayName}</span>
        </div>
        {!isVix && data.regime_label && (
          <span className={`text-[10px] font-semibold border rounded px-1.5 py-0.5 ${REGIME_COLORS[data.regime_label] || REGIME_COLORS.Range}`}>
            {data.regime_label}
          </span>
        )}
      </div>
      <div className="flex items-baseline gap-2 mb-1">
        <span className="text-xl font-bold text-white">
          {data.price != null ? data.price.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—'}
        </span>
      </div>
      {data.change_percent != null && (
        <div className={`text-xs font-medium mb-2 ${positive ? 'text-emerald-400' : 'text-rose-400'}`}>
          {positive ? '↗' : '↘'} {positive ? '+' : ''}{data.change_percent.toFixed(2)}%
        </div>
      )}
      <Sparkline values={data.sparkline} dates={data.sparkline_dates} positive={positive} />
      {isVix ? (
        <VixGauge label={data.regime_label} />
      ) : (
        <RangeBar low={data.range_18d_low} high={data.range_18d_high} current={data.price} />
      )}
    </div>
  );
}
