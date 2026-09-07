import { useEffect, useState } from 'react';
import {
  ComposedChart, LineChart, Bar, Line, XAxis, YAxis,
  ResponsiveContainer, ReferenceLine, Tooltip, CartesianGrid,
} from 'recharts';

// Uses recharts (already a dependency) rather than adding a new
// charting library -- ComposedChart's Bar component supports a
// two-value [min, max] dataKey ("range bars"), which is what makes a
// real OHLC candle possible here: the Bar below gets `range: [low,
// high]`, recharts maps that whole span to pixel y/height, and the
// Candle shape only has to place open/close as a linear interpolation
// inside that already-scaled span -- no second price->pixel scale
// needed inside the shape itself.

const API_BASE = import.meta.env.VITE_API_URL || '';

const EMA_COLORS = { ema10: '#2dd4bf', ema20: '#f59e0b', ema50: '#3b82f6', ema200: '#a78bfa' };
const EMA_LABELS = { ema10: '10', ema20: '20', ema50: '50', ema200: '200' };

function Candle(props) {
  const { x, y, width, height, payload } = props;
  const { open, close, high, low } = payload;
  if ([open, close, high, low].some((v) => v == null) || high === low) return null;
  const priceToY = (price) => y + (high - price) * (height / (high - low));
  const openY = priceToY(open);
  const closeY = priceToY(close);
  const bodyTop = Math.min(openY, closeY);
  const bodyHeight = Math.max(1, Math.abs(closeY - openY));
  const bodyWidth = Math.max(2, width * 0.6);
  const bodyX = x + (width - bodyWidth) / 2;
  const color = close >= open ? '#34d399' : '#fb7185';
  return (
    <g>
      <line x1={x + width / 2} x2={x + width / 2} y1={y} y2={y + height} stroke={color} strokeWidth={1} />
      <rect x={bodyX} y={bodyTop} width={bodyWidth} height={bodyHeight} fill={color} />
    </g>
  );
}

function fmtDate(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
}

function ChartTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs space-y-0.5">
      <div className="text-slate-400">{fmtDate(d.time)}</div>
      <div className="text-white whitespace-nowrap">
        O {d.open?.toFixed(2)} H {d.high?.toFixed(2)} L {d.low?.toFixed(2)} C {d.close?.toFixed(2)}
      </div>
      {d.rsi14 != null && <div className="text-slate-400">RSI {d.rsi14.toFixed(1)}</div>}
    </div>
  );
}

export default function ChartModal({ symbol, onClose }) {
  const [intervalType, setIntervalType] = useState('D');
  const [range, setRange] = useState('6M');
  const [showEma, setShowEma] = useState({ ema10: true, ema20: true, ema50: true, ema200: true });
  const [candles, setCandles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(`${API_BASE}/api/candles/${symbol}/?interval=${intervalType}&range=${range}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        if (cancelled) return;
        if (data.error) throw new Error(data.error);
        setCandles(data.candles || []);
        setError(null);
      })
      .catch((err) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [symbol, intervalType, range]);

  const chartData = candles.map((c) => ({ ...c, range: [c.low, c.high] }));
  const latest = candles[candles.length - 1];

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-slate-900 border border-slate-800 rounded-xl w-full max-w-3xl max-h-[90vh] overflow-y-auto p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-baseline gap-2">
            <span className="text-white font-bold text-lg">{symbol}</span>
            {latest && <span className="text-slate-300">₹{latest.close?.toFixed(2)}</span>}
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-white text-xl leading-none" aria-label="Close">×</button>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div className="flex gap-1">
            {['D', 'W'].map((v) => (
              <button
                key={v}
                onClick={() => setIntervalType(v)}
                className={`px-2.5 py-1 text-xs rounded-lg border ${intervalType === v ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' : 'text-slate-400 border-slate-700'}`}
              >
                {v === 'D' ? 'Daily' : 'Weekly'}
              </button>
            ))}
          </div>
          <div className="flex gap-1">
            {['3M', '6M', '12M'].map((v) => (
              <button
                key={v}
                onClick={() => setRange(v)}
                className={`px-2.5 py-1 text-xs rounded-lg border ${range === v ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' : 'text-slate-400 border-slate-700'}`}
              >
                {v}
              </button>
            ))}
          </div>
          <div className="flex gap-3">
            {Object.keys(EMA_COLORS).map((k) => (
              <label key={k} className="flex items-center gap-1 text-xs text-slate-400 cursor-pointer">
                <input
                  type="checkbox"
                  checked={showEma[k]}
                  onChange={() => setShowEma((s) => ({ ...s, [k]: !s[k] }))}
                  style={{ accentColor: EMA_COLORS[k] }}
                />
                {EMA_LABELS[k]}
              </label>
            ))}
          </div>
        </div>

        {loading && <div className="py-16 text-center text-slate-500 text-sm">Loading chart...</div>}
        {error && !loading && <div className="py-16 text-center text-rose-400 text-sm">{error}</div>}

        {!loading && !error && candles.length > 0 && (
          <>
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={chartData} syncId="chartmodal" margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="time" tickFormatter={fmtDate} tick={{ fill: '#64748b', fontSize: 11 }} minTickGap={30} />
                <YAxis domain={['auto', 'auto']} tick={{ fill: '#64748b', fontSize: 11 }} width={55} />
                <Tooltip content={<ChartTooltip />} />
                <Bar dataKey="range" shape={<Candle />} isAnimationActive={false} />
                {showEma.ema10 && <Line type="monotone" dataKey="ema10" stroke={EMA_COLORS.ema10} dot={false} strokeWidth={1.4} isAnimationActive={false} />}
                {showEma.ema20 && <Line type="monotone" dataKey="ema20" stroke={EMA_COLORS.ema20} dot={false} strokeWidth={1.4} isAnimationActive={false} />}
                {showEma.ema50 && <Line type="monotone" dataKey="ema50" stroke={EMA_COLORS.ema50} dot={false} strokeWidth={1.4} isAnimationActive={false} />}
                {showEma.ema200 && <Line type="monotone" dataKey="ema200" stroke={EMA_COLORS.ema200} dot={false} strokeWidth={1.4} isAnimationActive={false} />}
              </ComposedChart>
            </ResponsiveContainer>

            <div className="flex items-center justify-between mt-3 mb-1">
              <span className="text-xs text-slate-500">RSI (14)</span>
              {latest?.rsi14 != null && <span className="text-xs text-slate-300">{latest.rsi14.toFixed(1)}</span>}
            </div>
            <ResponsiveContainer width="100%" height={100}>
              <LineChart data={chartData} syncId="chartmodal" margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                <XAxis dataKey="time" tickFormatter={fmtDate} tick={{ fill: '#64748b', fontSize: 11 }} minTickGap={30} />
                <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 11 }} width={55} ticks={[30, 70]} />
                <ReferenceLine y={70} stroke="#475569" strokeDasharray="3 3" />
                <ReferenceLine y={30} stroke="#475569" strokeDasharray="3 3" />
                <Line type="monotone" dataKey="rsi14" stroke="#38bdf8" dot={false} strokeWidth={1.4} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </>
        )}

        {!loading && !error && candles.length === 0 && (
          <div className="py-16 text-center text-slate-500 text-sm">No chart data available.</div>
        )}
      </div>
    </div>
  );
}
