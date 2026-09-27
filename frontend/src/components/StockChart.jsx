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

export default function StockChart({ symbol }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);

  const [timeframe, setTimeframe] = useState('1d');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [meta, setMeta] = useState(null); // {latest_price, as_of, symbol}

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

    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  const loadCandles = useCallback(async (sym, tf) => {
    if (!sym) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/research/company/${sym}/candles/?timeframe=${tf}`);
      const data = await res.json();
      if (!res.ok || data.status !== 'ok') {
        setError(data.message || 'Chart data unavailable.');
        setMeta(null);
        if (candleSeriesRef.current) candleSeriesRef.current.setData([]);
        if (volumeSeriesRef.current) volumeSeriesRef.current.setData([]);
        return;
      }
      const candleData = data.candles.map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close }));
      const volumeData = data.candles.map(c => ({ time: c.time, value: c.volume, color: c.close >= c.open ? '#34d39980' : '#f8717180' }));
      if (candleSeriesRef.current) candleSeriesRef.current.setData(candleData);
      if (volumeSeriesRef.current) volumeSeriesRef.current.setData(volumeData);
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

      {error && (
        <div className="text-xs text-rose-400 bg-rose-500/10 rounded px-3 py-2 mb-2">{error}</div>
      )}

      <div ref={containerRef} className="w-full" style={{ minHeight: 380 }} />
    </div>
  );
}
