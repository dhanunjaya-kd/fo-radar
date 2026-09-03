import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Sep 3 2026: downsample() and buildChartPath() below are copied
// VERBATIM from IndexPriceChart.jsx (not reimplemented) -- that file's
// own comment notes both were independently tested (test_chart_range_
// logic.js / test_chart_coordinates.js) before being wired together.
// Reusing the exact same, already-proven math here rather than writing
// new coordinate logic for what is otherwise the same kind of line
// chart, just fed from a different data source (a single Fyers
// history() call for one option contract, not this project's own
// logged index snapshots).
function downsample(points, maxPoints = 500) {
  if (points.length <= maxPoints) return points;
  const step = Math.ceil(points.length / maxPoints);
  const result = [];
  for (let i = 0; i < points.length; i += step) result.push(points[i]);
  if (result[result.length - 1] !== points[points.length - 1]) {
    result.push(points[points.length - 1]);
  }
  return result;
}

function buildChartPath(values, width, height, padding = 4) {
  const clean = values.filter(v => v != null && !isNaN(v));
  if (clean.length < 2) return null;
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const range = max - min || 1;
  const usableWidth = width - padding * 2;
  const usableHeight = height - padding * 2;
  const stepX = usableWidth / (clean.length - 1);
  const coords = clean.map((v, i) => ({
    x: padding + i * stepX,
    y: padding + usableHeight - ((v - min) / range) * usableHeight,
  }));
  const path = coords.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  return { path, min, max, coords };
}

function fmtTime(unixSeconds) {
  const d = new Date(unixSeconds * 1000);
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true });
}

// Sep 3 2026: built after two failed attempts to send the user to an
// EXTERNAL site for this exact chart (trade.fyers.in has no per-symbol
// URL at all; a TradingView URL guess also failed real testing on a
// live signal). Renders the contract's own price chart INSIDE this app
// instead, from a real Fyers history() call this project already knows
// works for ACTIVE option contracts (confirmed via Fyers' own
// community forum + notice board -- expired-contract history is a
// separate, real Fyers limitation that doesn't apply here since every
// live signal is always for a currently-active contract).
export default function OptionPriceChart({ optionSymbol }) {
  const [candles, setCandles] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!optionSymbol) { setCandles(null); return; }
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetch(`${API_BASE}/api/option-history/?symbol=${encodeURIComponent(optionSymbol)}&resolution=5`)
      .then(res => res.ok ? res.json() : res.json().then(d => Promise.reject(new Error(d.error || `HTTP ${res.status}`))))
      .then(data => {
        if (cancelled) return;
        setCandles(data.candles || []);
      })
      .catch(e => { if (!cancelled) { setError(e.message); setCandles(null); } })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [optionSymbol]);

  const WIDTH = 380, HEIGHT = 140;
  const points = candles ? downsample(candles) : null;
  const chart = points ? buildChartPath(points.map(c => c.close), WIDTH, HEIGHT) : null;
  const latest = points && points.length > 0 ? points[points.length - 1].close : null;
  const first = points && points.length > 0 ? points[0].close : null;
  const change = latest != null && first != null ? latest - first : null;
  const isPos = (change ?? 0) >= 0;

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
      <div className="flex items-center justify-between mb-2">
        <p className="text-[10px] text-slate-500 uppercase tracking-wide">Option Price (5min)</p>
        {latest != null && (
          <div className="flex items-baseline gap-1.5">
            <span className="text-sm font-bold text-white tabular-nums">₹{latest.toFixed(2)}</span>
            {change != null && (
              <span className={`text-[10px] font-medium ${isPos ? 'text-emerald-400' : 'text-rose-400'}`}>
                {isPos ? '+' : ''}{change.toFixed(2)}
              </span>
            )}
          </div>
        )}
      </div>

      {loading ? (
        <div className="h-[140px] rounded-md bg-slate-800/40 animate-pulse" />
      ) : error ? (
        <div className="py-8 text-center text-xs text-slate-500">
          {error === 'Not authenticated with Fyers -- no data available'
            ? 'Not connected to Fyers right now.'
            : error}
        </div>
      ) : !chart ? (
        <div className="py-8 text-center text-xs text-slate-500">Not enough real data yet for this contract.</div>
      ) : (
        <div>
          <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full h-auto" style={{ maxHeight: HEIGHT }}>
            <path d={chart.path} fill="none" stroke={isPos ? '#34d399' : '#fb7185'} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div className="flex items-center justify-between text-[9px] text-slate-500 mt-1">
            <span>{fmtTime(points[0].time)}</span>
            <span>Low ₹{chart.min.toFixed(2)} · High ₹{chart.max.toFixed(2)}</span>
            <span>{fmtTime(points[points.length - 1].time)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
