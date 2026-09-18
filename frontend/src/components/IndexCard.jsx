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

function Sparkline({ values, positive }) {
  if (!values || values.length < 2) return <div className="h-16" />;
  const w = 280, h = 64, pad = 2;
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const points = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (w - pad * 2);
    const y = pad + (1 - (v - min) / range) * (h - pad * 2);
    return `${x},${y}`;
  });
  const color = positive ? '#34d399' : '#ef4444';
  const fillPoints = `${pad},${h} ${points.join(' ')} ${w - pad},${h}`;
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <polygon points={fillPoints} fill={color} opacity="0.12" />
      <polyline points={points.join(' ')} fill="none" stroke={color} strokeWidth="1.5" />
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

const REGIME_COLORS = { Bullish: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/25', Bearish: 'text-red-400 bg-red-500/10 border-red-500/25', Range: 'text-slate-400 bg-slate-500/10 border-slate-500/25' };
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
        <div className={`text-xs font-medium mb-2 ${positive ? 'text-emerald-400' : 'text-red-400'}`}>
          {positive ? '↗' : '↘'} {positive ? '+' : ''}{data.change_percent.toFixed(2)}%
        </div>
      )}
      <Sparkline values={data.sparkline} positive={positive} />
      {isVix ? (
        <VixGauge label={data.regime_label} />
      ) : (
        <RangeBar low={data.range_18d_low} high={data.range_18d_high} current={data.price} />
      )}
    </div>
  );
}
