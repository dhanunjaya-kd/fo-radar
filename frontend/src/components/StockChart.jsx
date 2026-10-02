import { useEffect, useRef, useState, useCallback } from 'react';
import { useTheme, toneFor } from './ThemeContext';
import { createChart, ColorType, CrosshairMode } from 'lightweight-charts';
import { ema, bollinger, psar } from '../utils/indicators';
import IndicatorPane, { PANE_DEFS } from './IndicatorPane';

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

// Sep 27 2026 fix: real, confirmed timezone bug. NSE trades 9:15am -
// 3:30pm IST. Fyers' Unix timestamps are correct UTC moments (9:15am
// IST = 03:45 UTC), but lightweight-charts' crosshair and axis labels
// display raw UTC by default, not IST -- so a real 9:15am market-open
// candle was showing as "03:45", making it look like the market was
// open at 3:45am. The underlying data was fine; only the display was
// wrong. Every time-formatting function below now explicitly forces
// Asia/Kolkata, so this is correct regardless of the machine's own
// system timezone rather than assuming it happens to be set to IST.
const IST_TIMEZONE = 'Asia/Kolkata';

function formatAsOf(unixTimestamp, timeframe) {
  if (!unixTimestamp) return '—';
  // Sep 27 2026 fix: real, confirmed cause of a misleading "5:30 AM"
  // timestamp on daily candles. A daily bar represents an entire
  // trading day, not one specific moment -- Fyers anchors it at
  // midnight UTC, which is a pure date marker, not a real trading
  // time. Converting that to IST (correctly, per the earlier
  // timezone fix) produces 00:00 UTC + 5:30 = 05:30 IST, a time that
  // never actually happened on that candle. For 1d/1w, show only the
  // date -- no time component to misrepresent.
  if (timeframe === '1d' || timeframe === '1w') {
    return new Date(unixTimestamp * 1000).toLocaleString('en-IN', { dateStyle: 'medium', timeZone: IST_TIMEZONE });
  }
  return new Date(unixTimestamp * 1000).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: IST_TIMEZONE });
}

function formatCrosshairTimeIST(time) {
  // lightweight-charts' Time here is a UTCTimestamp (whole seconds).
  const date = new Date(time * 1000);
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: IST_TIMEZONE, day: '2-digit', month: 'short', year: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date).replace(',', '');
}

function formatTickMarkTimeIST(time, tickMarkType) {
  const date = new Date(time * 1000);
  const opts = { timeZone: IST_TIMEZONE };
  switch (tickMarkType) {
    case 0: // Year
      return new Intl.DateTimeFormat('en-GB', { ...opts, year: 'numeric' }).format(date);
    case 1: // Month
      return new Intl.DateTimeFormat('en-GB', { ...opts, month: 'short', year: '2-digit' }).format(date);
    case 2: // DayOfMonth
      return new Intl.DateTimeFormat('en-GB', { ...opts, day: '2-digit', month: 'short' }).format(date);
    case 4: // TimeWithSeconds
      return new Intl.DateTimeFormat('en-GB', { ...opts, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(date);
    default: // Time
      return new Intl.DateTimeFormat('en-GB', { ...opts, hour: '2-digit', minute: '2-digit', hour12: false }).format(date);
  }
}

// Oct 2 2026: price-chart overlays. Each builds its line(s) from the candles already on screen (see
// utils/indicators.js -- checked against TA-Lib), so toggling one never triggers a new backend call.
// Sep 27 2026 original rule still holds: warm-up values are null, never invented.
const closesOf = (c) => c.map((x) => x.close);
const OVERLAYS = {
  ema10: { label: 'EMA10', color: '#fb923c', build: (c) => [{ color: '#fb923c', data: ema(closesOf(c), 10) }] },
  ema20: { label: 'EMA20', color: '#facc15', build: (c) => [{ color: '#facc15', data: ema(closesOf(c), 20) }] },
  ema50: { label: 'EMA50', color: '#38bdf8', build: (c) => [{ color: '#38bdf8', data: ema(closesOf(c), 50) }] },
  ema200: { label: 'EMA200', color: '#c084fc', build: (c) => [{ color: '#c084fc', data: ema(closesOf(c), 200) }] },
  bb: {
    label: 'Bollinger 20,2', color: '#94a3b8',
    build: (c) => { const b = bollinger(c); return [{ color: '#64748b', data: b.upper }, { color: '#94a3b8', data: b.mid, dashed: true }, { color: '#64748b', data: b.lower }]; },
  },
  psar: { label: 'PSAR', color: '#f472b6', build: (c) => [{ color: '#f472b6', data: psar(c), dots: true }] },
};
const DEFAULT_OVERLAYS = { ema10: false, ema20: true, ema50: true, ema200: true, bb: false, psar: false };   // EMA20/50/200 on by default, as before
const PREF_KEY = 'fo-radar-chart-indicators';

function loadPrefs() {
  try {
    const raw = JSON.parse(localStorage.getItem(PREF_KEY) || 'null');
    if (raw && typeof raw === 'object') {
      return {
        overlays: { ...DEFAULT_OVERLAYS, ...Object.fromEntries(Object.entries(raw.overlays || {}).filter(([k]) => k in OVERLAYS)) },
        panes: (raw.panes || []).filter((k) => k in PANE_DEFS),
      };
    }
  } catch { /* unreadable or blocked storage -> defaults */ }
  return { overlays: DEFAULT_OVERLAYS, panes: [] };
}

function StockChartInner({ symbol, compact = false }) {
  const { theme } = useTheme();
  const T = (hex) => toneFor(theme, hex);
  // Sep 27 2026 fix: THE actual, confirmed root cause of the
  // persistent blank chart, found by building a real React
  // reproduction of this exact pattern and running it in a headless
  // browser (not guessed). A plain useRef + a chart-creation effect
  // with an empty [] dependency array is a classic React trap here:
  // this component mounts with symbol=undefined on the very first
  // page load (before any search), the `if (!symbol) return null`
  // below means the container <div> never renders on that first
  // pass, so containerRef.current is still null when the one-time
  // effect runs -- and because its deps are [], it NEVER runs again,
  // even after a real symbol arrives and the container finally
  // exists. Confirmed empirically: the chart was NEVER created in
  // this scenario. A callback ref (via useState, not useRef) is the
  // correct fix -- React invokes it exactly when the DOM node
  // actually attaches, whenever that happens to be, so the effect
  // below (now keyed on containerEl) gets a real chance to run.
  const [containerEl, setContainerEl] = useState(null);
  const [chartReady, setChartReady] = useState(false);  // true once createChart() + series are actually set up -- see the race-condition note below
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const overlaySeriesRef = useRef({});  // { overlayKey: [lightweight-charts series, ...] } -- created on demand, removed when toggled off
  const [chartInstance, setChartInstance] = useState(null);   // state copy of the chart, so indicator strips can sync to it
  const [candles, setCandles] = useState([]);
  const [hoverTime, setHoverTime] = useState(null);

  const [timeframe, setTimeframe] = useState('1d');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [meta, setMeta] = useState(null); // {latest_price, as_of, symbol}
  const [hoverOHLC, setHoverOHLC] = useState(null); // {open, high, low, close} at crosshair, or null when not hovering
  const [prefs, setPrefs] = useState(loadPrefs);   // { overlays, panes } -- remembered between visits
  const overlays = prefs.overlays;
  const panes = prefs.panes;
  useEffect(() => { try { localStorage.setItem(PREF_KEY, JSON.stringify(prefs)); } catch { /* storage blocked */ } }, [prefs]);
  const toggleOverlay = (key) => setPrefs((p) => ({ ...p, overlays: { ...p.overlays, [key]: !p.overlays[key] } }));
  const togglePane = (key) => setPrefs((p) => ({ ...p, panes: p.panes.includes(key) ? p.panes.filter((k) => k !== key) : [...p.panes, key] }));

  // Chart instance created whenever the container DOM node actually
  // exists (see the callback-ref note above) -- NOT tied to mount
  // timing, so it works correctly regardless of whether a symbol was
  // available on the very first render.
  //
  // Sep 27 2026 fix: real, confirmed cause of a visible chart flicker
  // under React StrictMode (which this project's main.jsx wraps the
  // whole app in -- confirmed by reading it directly). StrictMode
  // deliberately double-invokes every effect in development: mount,
  // immediate cleanup, mount again. Proved this was actually
  // happening here with a real instrumented test: 14 canvas elements
  // were created over one mount, exactly 2x the 7 a single
  // createChart() call produces, with only 7 surviving -- meaning a
  // full chart was created and immediately torn down before the
  // surviving one replaced it. The actual chart creation is now
  // deferred by one animation frame, guarded by a `cancelled` flag
  // set in the cleanup. React's StrictMode cleanup+remount happens
  // synchronously, before the browser ever runs a scheduled
  // animation-frame callback -- so the discarded first pass's
  // deferred callback gets cancelled before it ever creates
  // anything, and only the surviving second pass actually builds a
  // chart. StrictMode still properly exercises mount/cleanup/remount
  // (nothing is being suppressed or worked around unsafely); the
  // expensive, visible work just no longer happens twice. This has
  // no effect in production builds, where StrictMode's double-invoke
  // doesn't happen and the deferred call simply fires once, on the
  // next frame, as normal.
  useEffect(() => {
    if (!containerEl) return;
    let cancelled = false;
    let chart = null;
    let resizeObserver = null;
    let handleCrosshairMove = null;

    const rafId = requestAnimationFrame(() => {
      if (cancelled) return;

      chart = createChart(containerEl, {
        // Sep 27 2026 correction: attributionLogo is a field INSIDE
        // the `layout` object (same interface as background/textColor/
        // fontSize) -- confirmed by reading its actual position in the
        // library's type definitions this time, not just that the
        // field existed somewhere. Previously placed at the top level
        // of createChart()'s options, where it doesn't exist, so it was
        // silently ignored (JS doesn't error on unknown object keys)
        // and the default (true, logo shown) stayed in effect the
        // whole time -- confirmed empirically: took a real screenshot
        // with the old placement (logo visible), moved it here, took
        // another screenshot (logo gone). This is lightweight-charts'
        // own default open-source attribution logo, not TradingView's
        // data or a live widget -- every candle on this chart comes
        // from this project's own Fyers/yfinance backend.
        layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: T('#94a3b8'), fontSize: 11, attributionLogo: false },
        grid: { vertLines: { color: T('#1e293b') }, horzLines: { color: T('#1e293b') } },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: { borderColor: T('#334155'), minimumWidth: 72 },   // fixed width so indicator strips below line up with it exactly
        timeScale: { borderColor: T('#334155'), timeVisible: true, secondsVisible: false, tickMarkFormatter: formatTickMarkTimeIST },
        localization: { timeFormatter: formatCrosshairTimeIST },
        width: containerEl.clientWidth,
        height: compact ? 300 : 380,
      });
      const candleSeries = chart.addCandlestickSeries({
        upColor: T('#34d399'), downColor: T('#f87171'), borderVisible: false,
        wickUpColor: T('#34d399'), wickDownColor: T('#f87171'),
      });
      const volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: 'volume' }, priceScaleId: '', color: T('#475569'),
      });
      volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      candleSeries.priceScale().applyOptions({ scaleMargins: { top: 0.05, bottom: 0.2 } });

      chartRef.current = chart;
      candleSeriesRef.current = candleSeries;
      volumeSeriesRef.current = volumeSeries;

      // Sep 27 2026: OHLC-on-hover, per explicit requirement ("clear
      // OHLC details on hover"). chart.subscribeCrosshairMove() and
      // params.seriesData -- both confirmed real, documented APIs by
      // reading this exact installed library version's own type
      // definitions before using them, not guessed.
      handleCrosshairMove = (param) => {
        setHoverTime(param.time || null);
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

      // ResizeObserver on the container -- a genuine, separate
      // improvement made in an earlier round (window 'resize' alone
      // misses pure React layout shifts), kept here since it's still
      // correct and useful alongside the callback-ref fix above; the
      // two address different failure modes.
      resizeObserver = new ResizeObserver((entries) => {
        const entry = entries[0];
        if (entry && entry.contentRect.width > 0) {
          chart.applyOptions({ width: entry.contentRect.width });
        }
      });
      resizeObserver.observe(containerEl);

      // Sep 27 2026: real, caught-before-delivery bug. Deferring
      // chart creation by a frame (the StrictMode double-creation fix
      // above) opened a race: a fast-resolving fetch in loadCandles()
      // could call setData() on candleSeriesRef.current while it was
      // still null, since this callback hadn't run yet -- the
      // existing `if (ref.current)` guards made it fail silently
      // (header showed the right price, canvas stayed empty).
      // Confirmed by actually reproducing it with a real render
      // before catching this. chartReady gates the data-loading
      // effect below so it simply doesn't start fetching until the
      // chart genuinely exists.
      setChartInstance(chart);
      setChartReady(true);
    });

    return () => {
      cancelled = true;
      cancelAnimationFrame(rafId);
      if (resizeObserver) resizeObserver.disconnect();
      if (chart && handleCrosshairMove) chart.unsubscribeCrosshairMove(handleCrosshairMove);
      if (chart) chart.remove();
      chartRef.current = null;
      overlaySeriesRef.current = {};   // they died with the chart; the sync effect recreates them on the next one
      setChartInstance(null);
      setChartReady(false);
    };
  }, [containerEl]);

  // compact (multi-pane) mode is shorter
  useEffect(() => { if (chartInstance) chartInstance.applyOptions({ height: compact ? 300 : 380 }); }, [compact, chartInstance]);


  const abortControllerRef = useRef(null);
  const latestRequestIdRef = useRef(0);
  const candleCacheRef = useRef({});  // {[`${symbol}:${timeframe}`]: data} -- in-memory, cleared on full page reload; not persisted (no browser storage per this environment's rules)
  const lastFitKeyRef = useRef(null);  // which symbol:timeframe key the view has already been auto-fit for

  // Extracted so the SAME rendering path is used for both an
  // immediately-shown cached value and a freshly-fetched one --
  // avoids two subtly-diverging copies of this logic.
  const applyChartData = useCallback((data) => {
    const candleData = data.candles.map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close }));
    const volumeData = data.candles.map(c => ({ time: c.time, value: c.volume, color: (c.close >= c.open ? T('#34d399') : T('#f87171')) + '80' }));
    if (candleSeriesRef.current) candleSeriesRef.current.setData(candleData);
    if (volumeSeriesRef.current) volumeSeriesRef.current.setData(volumeData);
    setCandles(data.candles);   // overlays and indicator strips compute from this
    // Sep 27 2026 fix: real, confirmed cause of chart "shaking" --
    // stale-while-revalidate calls applyChartData TWICE for the same
    // symbol/timeframe (once immediately with cached data, once again
    // moments later with the fresh fetch). fitContent() resetting the
    // zoom/pan BOTH times produced a visible jump. Now only auto-fits
    // the FIRST time a given symbol+timeframe is shown -- a routine
    // background refresh of data the user is already looking at
    // preserves whatever zoom/scroll position they're on, matching
    // the explicit "preserve zoom/scroll during routine updates"
    // requirement.
    const fitKey = `${data.symbol}:${data.timeframe}`;
    if (chartRef.current && lastFitKeyRef.current !== fitKey) {
      chartRef.current.timeScale().fitContent();
      lastFitKeyRef.current = fitKey;
    }
    setMeta({ latest_price: data.latest_price, as_of: data.as_of, symbol: data.symbol, source: data.source, timeframe: data.timeframe });
  }, []);

  const loadCandles = useCallback(async (sym, tf, { bypassCache = false } = {}) => {
    if (!sym) return;
    // Sep 27 2026 fix: real race condition -- rapidly clicking through
    // timeframes (or switching stocks quickly) fired multiple
    // concurrent fetches with no cancellation, so a SLOWER older
    // request could resolve AFTER a newer one and overwrite the chart
    // with the wrong timeframe/symbol's data. Two layers: an
    // AbortController genuinely cancels the superseded network
    // request (saves bandwidth and backend load, not just ignored
    // client-side), and a request-id guard discards any response that
    // somehow still resolves after being superseded.
    if (abortControllerRef.current) abortControllerRef.current.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const requestId = ++latestRequestIdRef.current;

    setError(null);
    setHoverOHLC(null);  // Sep 27 2026 fix: without this, hovering the OLD symbol's chart then switching symbols left a stale OHLC readout visible until the next mouse move.

    // Sep 27 2026 addition: stale-while-revalidate. If this exact
    // symbol+timeframe was seen before in this session, render it
    // IMMEDIATELY (no blank chart, no spinner wait) while a fresh
    // request still goes out in the background below -- explicit
    // requirement: "cached chart should appear almost immediately."
    // setLoading is deliberately NOT set true here when a cached
    // value exists, since there's already something real on screen;
    // it's set true only for a genuine first-time (empty-chart) fetch.
    const cacheKey = `${sym}:${tf}`;
    const cached = bypassCache ? null : candleCacheRef.current[cacheKey];
    if (cached) {
      applyChartData(cached);
    } else {
      setLoading(true);
    }

    try {
      const res = await fetch(`${API_BASE}/api/research/company/${sym}/candles/?timeframe=${tf}`, { signal: controller.signal });
      if (requestId !== latestRequestIdRef.current) return;  // superseded by a newer request while this one was in flight
      const data = await res.json();
      if (requestId !== latestRequestIdRef.current) return;  // re-checked after the second await, same reason
      if (!res.ok || data.status !== 'ok') {
        // Only show the error / clear the chart if there was NO cached
        // value already on screen -- a background refresh failing
        // (e.g. a transient rate limit) shouldn't blank out data the
        // user can already see and that's still reasonably valid.
        if (!cached) {
          setError(data.message || 'Chart data unavailable.');
          setMeta(null);
          if (candleSeriesRef.current) candleSeriesRef.current.setData([]);
          if (volumeSeriesRef.current) volumeSeriesRef.current.setData([]);
          setCandles([]);
        }
        return;
      }
      candleCacheRef.current[cacheKey] = data;
      applyChartData(data);
    } catch (e) {
      if (e.name === 'AbortError') return;  // expected when superseded -- not a real error, don't show one
      if (!cached) {
        setError('Could not reach the chart data service.');
        setMeta(null);
      }
    } finally {
      // Guarded too: without this, an aborted/superseded request's
      // finally block could still fire AFTER a newer request has
      // already started, incorrectly clearing loading=false while the
      // newer fetch is genuinely still in flight.
      if (requestId === latestRequestIdRef.current) setLoading(false);
    }
  }, [applyChartData]);

  useEffect(() => {
    if (!chartReady) return;  // real fix for a race caught before delivery: don't fetch until the chart genuinely exists to receive the data (see the chart-creation effect's notes above)
    loadCandles(symbol, timeframe);
    // Sep 27 2026: abort any in-flight fetch on unmount too, not just
    // on the next call -- without this, navigating away from the page
    // mid-fetch would let the request finish anyway and attempt a
    // setState on an unmounted component.
    return () => {
      if (abortControllerRef.current) abortControllerRef.current.abort();
    };
  }, [symbol, timeframe, loadCandles, chartReady]);

  // Overlays: create / remove / refill lightweight-charts series to match the toggles and the candles on
  // screen. Pure client-side -- no refetch, no duplicate requests when a toggle is clicked.
  useEffect(() => {
    const chart = chartInstance;
    if (!chart) return;
    const toSeriesData = (values) => values.map((v, i) => (v == null ? { time: candles[i].time } : { time: candles[i].time, value: v }));
    for (const [key, def] of Object.entries(OVERLAYS)) {
      const existing = overlaySeriesRef.current[key];
      if (!overlays[key]) {
        if (existing) { existing.forEach((sr) => chart.removeSeries(sr)); delete overlaySeriesRef.current[key]; }
        continue;
      }
      if (!candles.length) continue;
      const specs = def.build(candles);
      let list = existing;
      if (!list) {
        list = specs.map((sp) => chart.addLineSeries({
          color: T(sp.color), lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
          lineStyle: sp.dashed ? 2 : 0,
          ...(sp.dots ? { lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 1.6 } : {}),
        }));
        overlaySeriesRef.current[key] = list;
      }
      specs.forEach((sp, i) => list[i].setData(toSeriesData(sp.data)));
    }
  }, [overlays, candles, chartInstance]);

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
                as of {formatAsOf(meta.as_of, meta.timeframe)} — historical, not live-streamed
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
            onClick={() => loadCandles(symbol, timeframe, { bypassCache: true })} disabled={loading}
            className="px-2.5 py-1 text-[11px] rounded bg-slate-950/60 border border-slate-700/50 text-slate-300 hover:text-white disabled:opacity-50"
          >
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-1 px-1">
        <span className="text-[9px] text-slate-600 uppercase tracking-wide">Overlays</span>
        {Object.entries(OVERLAYS).map(([key, def]) => (
          <button key={key} onClick={() => toggleOverlay(key)} className={`flex items-center gap-1 text-[10px] ${overlays[key] ? 'text-slate-300' : 'text-slate-600 hover:text-slate-400'}`}>
            <span className="w-2.5 h-0.5" style={{ backgroundColor: overlays[key] ? T(def.color) : T('#475569') }} />
            {def.label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-2 px-1">
        <span className="text-[9px] text-slate-600 uppercase tracking-wide">Indicators</span>
        {Object.entries(PANE_DEFS).map(([key, def]) => (
          <button key={key} onClick={() => togglePane(key)}
            className={`text-[10px] px-1.5 py-0.5 rounded border ${panes.includes(key) ? 'text-emerald-300 border-emerald-500/50 bg-emerald-500/10' : 'text-slate-500 border-slate-700 hover:text-slate-300 hover:border-slate-500'}`}>
            {def.label.split(' ')[0]}
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

      <div ref={setContainerEl} className="w-full" style={{ minHeight: compact ? 300 : 380 }} />
      {panes.map((id) => (
        <IndicatorPane key={`${symbol}-${id}`} id={id} candles={candles} mainChart={chartInstance} hoverTime={hoverTime} onHoverTime={setHoverTime}
          onClose={() => togglePane(id)} height={compact ? 100 : 120} />
      ))}
    </div>
  );
}


// The lightweight-charts canvases take their colours as plain options, so a theme switch simply remounts
// the chart (one candle refetch) -- far more robust than re-colouring every series in place.
export default function StockChart(props) {
  const { theme } = useTheme();
  return <StockChartInner key={theme} {...props} />;
}
