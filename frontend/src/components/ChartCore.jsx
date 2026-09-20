import { useEffect, useState } from 'react';
import {
  ComposedChart, LineChart, Bar, Line, XAxis, YAxis,
  ResponsiveContainer, ReferenceLine, Tooltip, CartesianGrid, Cell,
} from 'recharts';

// Sep 19 2026: factored out of ChartModal.jsx so the new full-page
// Charts tab and the existing popup modal share ONE implementation
// instead of two copies drifting apart. Nothing about the chart
// logic itself changed in this split -- same fetch, same candle
// math, same EMA/RSI rendering; only the modal's own overlay/close
// button moved out into ChartModal.jsx, which now just wraps this.

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

function ChartTooltip({ active, payload, isIntraday }) {
  if (!active || !payload || !payload.length) return null;
  const d = payload[0].payload;
  const when = isIntraday
    ? new Date(d.time * 1000).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
    : fmtDate(d.time);
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs space-y-0.5">
      <div className="text-slate-400">{when}</div>
      <div className="text-white whitespace-nowrap">
        O {d.open?.toFixed(2)} H {d.high?.toFixed(2)} L {d.low?.toFixed(2)} C {d.close?.toFixed(2)}
      </div>
      {d.rsi14 != null && <div className="text-slate-400">RSI {d.rsi14.toFixed(1)}</div>}
    </div>
  );
}

// priceHeight/rsiHeight let the full-page version render noticeably
// bigger than the modal's compact 280/100 -- same component either way.
export default function ChartCore({ symbol, priceHeight = 280, rsiHeight = 100 }) {
  const [intervalType, setIntervalType] = useState('D');
  const [range, setRange] = useState('6M');
  const [showEma, setShowEma] = useState({ ema10: true, ema20: true, ema50: true, ema200: true });
  const [showBB, setShowBB] = useState(false);
  const [showMACD, setShowMACD] = useState(false);
  const [showADX, setShowADX] = useState(false);
  const [showStochRSI, setShowStochRSI] = useState(false);
  const [showCCI, setShowCCI] = useState(false);
  const [candles, setCandles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const isIntraday = intervalType === '15' || intervalType === '30';
  const RANGE_OPTIONS = isIntraday ? ['1D', '5D'] : ['1D', '3M', '6M', 'YTD', '12M'];
  const selectInterval = (v) => {
    setIntervalType(v);
    const nowIntraday = v === '15' || v === '30';
    setRange(nowIntraday ? '1D' : '6M');
  };
  const selectRange = (v) => {
    if (v === '1D' && !isIntraday) setIntervalType('15');
    setRange(v);
  };

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
  const fmtTick = isIntraday
    ? (epochSeconds) => new Date(epochSeconds * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
    : fmtDate;

  return (
    <div>
      <div className="flex items-baseline gap-2 mb-3">
        <span className="text-white font-bold text-lg">{symbol}</span>
        {latest && <span className="text-slate-300">₹{latest.close?.toFixed(2)}</span>}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="flex gap-1">
          {[['D', 'Daily'], ['W', 'Weekly'], ['15', '15m'], ['30', '30m']].map(([v, label]) => (
            <button
              key={v}
              onClick={() => selectInterval(v)}
              className={`px-2.5 py-1 text-xs rounded-lg border ${intervalType === v ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' : 'text-slate-400 border-slate-700'}`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex gap-1">
          {RANGE_OPTIONS.map((v) => (
            <button
              key={v}
              onClick={() => selectRange(v)}
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
          <label className="flex items-center gap-1 text-xs text-slate-400 cursor-pointer">
            <input type="checkbox" checked={showBB} onChange={() => setShowBB(v => !v)} style={{ accentColor: '#94a3b8' }} />
            BB
          </label>
          <label className="flex items-center gap-1 text-xs text-slate-400 cursor-pointer">
            <input type="checkbox" checked={showMACD} onChange={() => setShowMACD(v => !v)} style={{ accentColor: '#38bdf8' }} />
            MACD
          </label>
          <label className="flex items-center gap-1 text-xs text-slate-400 cursor-pointer">
            <input type="checkbox" checked={showADX} onChange={() => setShowADX(v => !v)} style={{ accentColor: '#f472b6' }} />
            ADX
          </label>
          <label className="flex items-center gap-1 text-xs text-slate-400 cursor-pointer">
            <input type="checkbox" checked={showStochRSI} onChange={() => setShowStochRSI(v => !v)} style={{ accentColor: '#a3e635' }} />
            StochRSI
          </label>
          <label className="flex items-center gap-1 text-xs text-slate-400 cursor-pointer">
            <input type="checkbox" checked={showCCI} onChange={() => setShowCCI(v => !v)} style={{ accentColor: '#fb923c' }} />
            CCI
          </label>
        </div>
      </div>

      {loading && <div className="py-16 text-center text-slate-500 text-sm">Loading chart...</div>}
      {error && !loading && <div className="py-16 text-center text-rose-400 text-sm">{error}</div>}

      {!loading && !error && candles.length > 0 && (
        <>
          <ResponsiveContainer width="100%" height={priceHeight}>
            <ComposedChart data={chartData} syncId={`chart-${symbol}`} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="time" tickFormatter={fmtTick} tick={{ fill: '#64748b', fontSize: 11 }} minTickGap={30} />
              <YAxis domain={['auto', 'auto']} tick={{ fill: '#64748b', fontSize: 11 }} width={55} />
              <Tooltip content={<ChartTooltip isIntraday={isIntraday} />} />
              <Bar dataKey="range" shape={<Candle />} isAnimationActive={false} />
              {showEma.ema10 && <Line type="monotone" dataKey="ema10" stroke={EMA_COLORS.ema10} dot={false} strokeWidth={1.4} isAnimationActive={false} />}
              {showEma.ema20 && <Line type="monotone" dataKey="ema20" stroke={EMA_COLORS.ema20} dot={false} strokeWidth={1.4} isAnimationActive={false} />}
              {showEma.ema50 && <Line type="monotone" dataKey="ema50" stroke={EMA_COLORS.ema50} dot={false} strokeWidth={1.4} isAnimationActive={false} />}
              {showEma.ema200 && <Line type="monotone" dataKey="ema200" stroke={EMA_COLORS.ema200} dot={false} strokeWidth={1.4} isAnimationActive={false} />}
              {showBB && <Line type="monotone" dataKey="bb_upper" stroke="#94a3b8" strokeDasharray="3 3" dot={false} strokeWidth={1} isAnimationActive={false} />}
              {showBB && <Line type="monotone" dataKey="bb_mid" stroke="#94a3b8" dot={false} strokeWidth={1} isAnimationActive={false} />}
              {showBB && <Line type="monotone" dataKey="bb_lower" stroke="#94a3b8" strokeDasharray="3 3" dot={false} strokeWidth={1} isAnimationActive={false} />}
            </ComposedChart>
          </ResponsiveContainer>

          <div className="flex items-center justify-between mt-3 mb-1">
            <span className="text-xs text-slate-500">RSI (14)</span>
            {latest?.rsi14 != null && <span className="text-xs text-slate-300">{latest.rsi14.toFixed(1)}</span>}
          </div>
          <ResponsiveContainer width="100%" height={rsiHeight}>
            <LineChart data={chartData} syncId={`chart-${symbol}`} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <XAxis dataKey="time" tickFormatter={fmtTick} tick={{ fill: '#64748b', fontSize: 11 }} minTickGap={30} />
              <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 11 }} width={55} ticks={[30, 70]} />
              <ReferenceLine y={70} stroke="#475569" strokeDasharray="3 3" />
              <ReferenceLine y={30} stroke="#475569" strokeDasharray="3 3" />
              <Line type="monotone" dataKey="rsi14" stroke="#38bdf8" dot={false} strokeWidth={1.4} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>

          {showMACD && (
            <>
              <div className="flex items-center justify-between mt-3 mb-1">
                <span className="text-xs text-slate-500">MACD (12, 26, 9)</span>
                {latest?.macd_line != null && (
                  <span className="text-xs text-slate-300">
                    {latest.macd_line.toFixed(2)} / {latest.macd_signal?.toFixed(2)}
                  </span>
                )}
              </div>
              <ResponsiveContainer width="100%" height={rsiHeight}>
                <ComposedChart data={chartData} syncId={`chart-${symbol}`} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <XAxis dataKey="time" tickFormatter={fmtTick} tick={{ fill: '#64748b', fontSize: 11 }} minTickGap={30} />
                  <YAxis domain={['auto', 'auto']} tick={{ fill: '#64748b', fontSize: 11 }} width={55} />
                  <ReferenceLine y={0} stroke="#475569" strokeDasharray="3 3" />
                  <Bar dataKey="macd_hist" isAnimationActive={false}>
                    {chartData.map((d, i) => (
                      <Cell key={i} fill={(d.macd_hist ?? 0) >= 0 ? '#34d399' : '#fb7185'} />
                    ))}
                  </Bar>
                  <Line type="monotone" dataKey="macd_line" stroke="#38bdf8" dot={false} strokeWidth={1.4} isAnimationActive={false} />
                  <Line type="monotone" dataKey="macd_signal" stroke="#f59e0b" dot={false} strokeWidth={1.4} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </>
          )}

          {showADX && (
            <>
              <div className="flex items-center justify-between mt-3 mb-1">
                <span className="text-xs text-slate-500">ADX (14)</span>
                {latest?.adx14 != null && <span className="text-xs text-slate-300">{latest.adx14.toFixed(1)}</span>}
              </div>
              <ResponsiveContainer width="100%" height={rsiHeight}>
                <LineChart data={chartData} syncId={`chart-${symbol}`} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <XAxis dataKey="time" tickFormatter={fmtTick} tick={{ fill: '#64748b', fontSize: 11 }} minTickGap={30} />
                  <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 11 }} width={55} ticks={[25]} />
                  <ReferenceLine y={25} stroke="#475569" strokeDasharray="3 3" />
                  <Line type="monotone" dataKey="adx14" stroke="#f472b6" dot={false} strokeWidth={1.6} isAnimationActive={false} />
                  <Line type="monotone" dataKey="plus_di" stroke="#34d399" dot={false} strokeWidth={1} isAnimationActive={false} />
                  <Line type="monotone" dataKey="minus_di" stroke="#fb7185" dot={false} strokeWidth={1} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </>
          )}

          {showStochRSI && (
            <>
              <div className="flex items-center justify-between mt-3 mb-1">
                <span className="text-xs text-slate-500">Stoch RSI (14, 14, 3, 3)</span>
                {latest?.stochrsi_k != null && <span className="text-xs text-slate-300">{latest.stochrsi_k.toFixed(1)}</span>}
              </div>
              <ResponsiveContainer width="100%" height={rsiHeight}>
                <LineChart data={chartData} syncId={`chart-${symbol}`} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <XAxis dataKey="time" tickFormatter={fmtTick} tick={{ fill: '#64748b', fontSize: 11 }} minTickGap={30} />
                  <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 11 }} width={55} ticks={[20, 80]} />
                  <ReferenceLine y={80} stroke="#475569" strokeDasharray="3 3" />
                  <ReferenceLine y={20} stroke="#475569" strokeDasharray="3 3" />
                  <Line type="monotone" dataKey="stochrsi_k" stroke="#a3e635" dot={false} strokeWidth={1.4} isAnimationActive={false} />
                  <Line type="monotone" dataKey="stochrsi_d" stroke="#f59e0b" dot={false} strokeWidth={1.4} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </>
          )}

          {showCCI && (
            <>
              <div className="flex items-center justify-between mt-3 mb-1">
                <span className="text-xs text-slate-500">CCI (20)</span>
                {latest?.cci20 != null && <span className="text-xs text-slate-300">{latest.cci20.toFixed(1)}</span>}
              </div>
              <ResponsiveContainer width="100%" height={rsiHeight}>
                <LineChart data={chartData} syncId={`chart-${symbol}`} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <XAxis dataKey="time" tickFormatter={fmtTick} tick={{ fill: '#64748b', fontSize: 11 }} minTickGap={30} />
                  <YAxis domain={['auto', 'auto']} tick={{ fill: '#64748b', fontSize: 11 }} width={55} />
                  <ReferenceLine y={100} stroke="#475569" strokeDasharray="3 3" />
                  <ReferenceLine y={-100} stroke="#475569" strokeDasharray="3 3" />
                  <Line type="monotone" dataKey="cci20" stroke="#fb923c" dot={false} strokeWidth={1.4} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </>
          )}
        </>
      )}

      {!loading && !error && candles.length === 0 && (
        <div className="py-16 text-center text-slate-500 text-sm">No chart data available.</div>
      )}
    </div>
  );
}
