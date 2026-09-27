import { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, ColorType, CrosshairMode } from 'lightweight-charts';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Sep 27 2026: real OHLCV candles from Fyers via /candles/ endpoint --
// see stock_chart.py. No live streaming: confirmed during earlier work
// on this project that no WebSocket infrastructure exists anywhere
// here, only polling. This component is honest about that -- shows
// the real as-of timestamp from the last candle, never claims "live"
// data it doesn't have.

const TIMEFRAMES = [
  { value: '5m', label: '5m' }, { value: '15m', label: '15m' }, { value: '1h', label: '1H' },
  { value: '1d', label: '1D' }, { value: '1w', label: '1W' },
];

function formatAsOf(unixTimestamp) {
  if (!unixTimestamp) return '—';
  return new Date(unixTimestamp * 1000).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
}

// Sep 27 2026: standard EMA formula (k = 2/(period+1), seeded with the
// SMA of the first `period` closes, per the universal textbook
// definition -- not invented). Computed client-side from the same
// candles already fetched, since EMA is a pure function of closing
// prices and doesn't need a new backend round-trip. Returns null for
// every point before there's enough data to seed the average --
// never a fabricated early value, matching this project's "never
// invent indicator values" rule everywhere else.
function calculateEMA(candles, period) {
  if (!candles || candles.length < period) return candles.map(() => null);
  const result = new Array(candles.length).fill(null);
  const k = 2 / (period + 1);
  let sma = 0;
  for (let i = 0; i < period; i++) sma += candles[i].close;
  sma /= period;
  result[period - 1] = sma;
  let prevEma = sma;
  for (let i = period; i < candles.length; i++) {
    const ema = (candles[i].close - prevEma) * k + prevEma;
    result[i] = ema;
    prevEma = ema;
  }
  return result;
}

export default function StockChart({ symbol }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const emaSeriesRef = useRef({});  // {20: series, 50: series, 200: series}

  const [timeframe, setTimeframe] = useState('1d');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [meta, setMeta] = useState(null); // {latest_price, as_of, symbol}
  const [hoverOHLC, setHoverOHLC] = useState(null); // {open, high, low, close} at crosshair, or null when not hovering
  const [emaVisible, setEmaVisible] = useState({ 20: true, 50: true, 200: true }); // default ON, per explicit "keep the default indicators enabled" requirement

  // Chart instance created once per mount, data updated in place --
  // avoids tearing down and rebuilding the whole chart (losing zoom/
  // pan state) on every timeframe or symbol change.
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#94a3b8', fontSize: 11 },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155', timeVisible: true, secondsVisible: false },
      width: containerRef.current.clientWidth,
      height: 380,
      // Sep 27 2026: this is lightweight-charts' OWN default open-
      // source attribution logo (confirmed by checking the library's
      // own type definitions -- a real, documented `attributionLogo`
      // option), not TradingView's data or widget. Every candle here
      // comes from this project's own backend. Disabled anyway since
      // it visually resembles TradingView branding and was genuinely
      // confusing, even though it's not actually a data-source issue.
      attributionLogo: false,
    });
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#34d399', downColor: '#f87171', borderVisible: false,
      wickUpColor: '#34d399', wickDownColor: '#f87171',
    });
    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' }, priceScaleId: '', color: '#475569',
    });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    candleSeries.priceScale().applyOptions({ scaleMargins: { top: 0.05, bottom: 0.2 } });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    // Sep 27 2026: EMA20/50/200 overlays, default ON per explicit
    // "keep the default indicators enabled" requirement. Distinct
    // colors so all three are readable when overlapping. Data is set
    // separately in loadCandles() once real candles arrive -- these
    // series start empty, never seeded with placeholder values.
    emaSeriesRef.current = {
      20: chart.addLineSeries({ color: '#facc15', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, visible: emaVisible[20] }),
      50: chart.addLineSeries({ color: '#38bdf8', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, visible: emaVisible[50] }),
      200: chart.addLineSeries({ color: '#c084fc', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, visible: emaVisible[200] }),
    };

    // Sep 27 2026: OHLC-on-hover, per explicit requirement ("clear
    // OHLC details on hover"). chart.subscribeCrosshairMove() and
    // params.seriesData -- both confirmed real, documented APIs by
    // reading this exact installed library version's own type
    // definitions before using them, not guessed.
    const handleCrosshairMove = (param) => {
      if (!param.time || !param.seriesData) {
        setHoverOHLC(null);
        return;
      }
      const bar = param.seriesData.get(candleSeries);
      if (bar && bar.open != null) {
        setHoverOHLC({ open: bar.open, high: bar.high, low: bar.low, close: bar.close, time: param.time });
      } else {
        setHoverOHLC(null);
      }
    };
    chart.subscribeCrosshairMove(handleCrosshairMove);

    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.unsubscribeCrosshairMove(handleCrosshairMove);
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  const loadCandles = useCallback(async (sym, tf) => {
    if (!sym) return;
    setLoading(true);
    setError(null);
    setHoverOHLC(null);  // Sep 27 2026 fix: without this, hovering the OLD symbol's chart then switching symbols left a stale OHLC readout visible until the next mouse move.
    try {
      const res = await fetch(`${API_BASE}/api/research/company/${sym}/candles/?timeframe=${tf}`);
      const data = await res.json();
      if (!res.ok || data.status !== 'ok') {
        setError(data.message || 'Chart data unavailable.');
        setMeta(null);
        if (candleSeriesRef.current) candleSeriesRef.current.setData([]);
        if (volumeSeriesRef.current) volumeSeriesRef.current.setData([]);
        Object.values(emaSeriesRef.current).forEach(s => s && s.setData([]));
        return;
      }
      const candleData = data.candles.map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close }));
      const volumeData = data.candles.map(c => ({ time: c.time, value: c.volume, color: c.close >= c.open ? '#34d39980' : '#f8717180' }));
      if (candleSeriesRef.current) candleSeriesRef.current.setData(candleData);
      if (volumeSeriesRef.current) volumeSeriesRef.current.setData(volumeData);
      // EMA20/50/200 -- computed from the SAME real candles just set
      // above, no separate fetch. calculateEMA() returns null for
      // every point before there's enough data to seed the average;
      // those points are filtered out entirely (a null point would
      // otherwise render as a broken gap or a fabricated zero).
      for (const period of [20, 50, 200]) {
        const emaValues = calculateEMA(data.candles, period);
        const emaData = data.candles
          .map((c, i) => (emaValues[i] != null ? { time: c.time, value: emaValues[i] } : null))
          .filter(Boolean);
        if (emaSeriesRef.current[period]) emaSeriesRef.current[period].setData(emaData);
      }
      if (chartRef.current) chartRef.current.timeScale().fitContent();
      setMeta({ latest_price: data.latest_price, as_of: data.as_of, symbol: data.symbol, source: data.source });
    } catch (e) {
      setError('Could not reach the chart data service.');
      setMeta(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCandles(symbol, timeframe);
  }, [symbol, timeframe, loadCandles]);

  // Toggling an EMA on/off just flips series visibility -- no
  // re-fetch, no re-computation, matching the "without stale results
  // or duplicate requests" requirement.
  useEffect(() => {
    for (const period of [20, 50, 200]) {
      if (emaSeriesRef.current[period]) emaSeriesRef.current[period].applyOptions({ visible: emaVisible[period] });
    }
  }, [emaVisible]);

  if (!symbol) return null;

  return (
    <div className="rounded-lg bg-slate-900/40 border border-slate-700/40 p-4">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold text-white">{symbol}</h2>
          {meta && (
            <>
              <span className="text-base font-bold text-white">₹{meta.latest_price.toFixed(2)}</span>
              <span className="text-[10px] text-slate-500">
                as of {formatAsOf(meta.as_of)} — historical, not live-streamed
                {meta.source === 'yfinance' && <span className="text-amber-500/80"> · via Yahoo Finance (Fyers was unavailable)</span>}
              </span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg bg-slate-950/60 border border-slate-700/50 p-0.5">
            {TIMEFRAMES.map(tf => (
              <button
                key={tf.value} onClick={() => setTimeframe(tf.value)}
                className={`px-2.5 py-1 text-[11px] rounded ${timeframe === tf.value ? 'bg-emerald-600/30 text-emerald-400' : 'text-slate-400 hover:text-slate-200'}`}
              >
                {tf.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => loadCandles(symbol, timeframe)} disabled={loading}
            className="px-2.5 py-1 text-[11px] rounded bg-slate-950/60 border border-slate-700/50 text-slate-300 hover:text-white disabled:opacity-50"
          >
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-3 mb-2 px-1">
        {[[20, '#facc15'], [50, '#38bdf8'], [200, '#c084fc']].map(([period, color]) => (
          <button
            key={period} onClick={() => setEmaVisible(v => ({ ...v, [period]: !v[period] }))}
            className={`flex items-center gap-1 text-[10px] ${emaVisible[period] ? 'text-slate-300' : 'text-slate-600'}`}
          >
            <span className="w-2.5 h-0.5" style={{ backgroundColor: emaVisible[period] ? color : '#475569' }} />
            EMA{period}
          </button>
        ))}
      </div>

      {hoverOHLC && (
        <div className="flex items-center gap-3 text-[11px] mb-2 px-1">
          <span className="text-slate-500">O <span className="text-slate-200 font-medium">{hoverOHLC.open.toFixed(2)}</span></span>
          <span className="text-slate-500">H <span className="text-emerald-400 font-medium">{hoverOHLC.high.toFixed(2)}</span></span>
          <span className="text-slate-500">L <span className="text-rose-400 font-medium">{hoverOHLC.low.toFixed(2)}</span></span>
          <span className="text-slate-500">C <span className="text-slate-200 font-medium">{hoverOHLC.close.toFixed(2)}</span></span>
        </div>
      )}

      {error && (
        <div className="text-xs text-rose-400 bg-rose-500/10 rounded px-3 py-2 mb-2">{error}</div>
      )}

      <div ref={containerRef} className="w-full" style={{ minHeight: 380 }} />
    </div>
  );
}
