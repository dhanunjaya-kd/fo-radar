import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, CrosshairMode } from 'lightweight-charts';
import { rsi, macd, adx, stochRsi, cci, mfi, aroon } from '../utils/indicators';

// Oct 2 2026: one indicator drawn in its own strip under the price chart (RSI, MACD, ADX, StochRSI, CCI,
// MFI, Aroon). Each strip is a separate lightweight-charts instance whose time scale is kept in lock-step
// with the main chart's, so scrolling/zooming either moves all of them. Every series is given a data point
// for EVERY candle (a bare {time} where the indicator is still warming up), so logical bar indexes line up
// exactly across charts. Values are computed client-side (utils/indicators.js, checked against TA-Lib).

const PURPLE = '#a78bfa', GREEN = '#34d399', RED = '#f87171', AMBER = '#fbbf24', SKY = '#38bdf8', SLATE = '#94a3b8';

export const PANE_DEFS = {
  rsi: {
    label: 'RSI 14', levels: [70, 50, 30], range: [0, 100],
    build: (c) => [{ id: 'rsi', name: 'RSI', color: PURPLE, data: rsi(c, 14) }],
  },
  macd: {
    label: 'MACD 12,26,9', levels: [0],
    build: (c) => {
      const m = macd(c);
      return [
        { id: 'hist', name: 'Hist', kind: 'hist', data: m.hist },
        { id: 'macd', name: 'MACD', color: SKY, data: m.macd },
        { id: 'signal', name: 'Signal', color: AMBER, data: m.signal },
      ];
    },
  },
  adx: {
    label: 'ADX 14', levels: [25], range: [0, 100],
    build: (c) => {
      const a = adx(c, 14);
      return [
        { id: 'adx', name: 'ADX', color: '#e2e8f0', width: 2, data: a.adx },
        { id: 'pdi', name: '+DI', color: GREEN, data: a.plusDI },
        { id: 'mdi', name: '−DI', color: RED, data: a.minusDI },
      ];
    },
  },
  stochrsi: {
    label: 'Stoch RSI', levels: [80, 20], range: [0, 100],
    build: (c) => {
      const s = stochRsi(c);
      return [{ id: 'k', name: '%K', color: SKY, data: s.k }, { id: 'd', name: '%D', color: AMBER, data: s.d }];
    },
  },
  cci: {
    label: 'CCI 20', levels: [100, 0, -100],
    build: (c) => [{ id: 'cci', name: 'CCI', color: '#f472b6', data: cci(c, 20) }],
  },
  mfi: {
    label: 'MFI 14', levels: [80, 20], range: [0, 100],
    build: (c) => [{ id: 'mfi', name: 'MFI', color: '#2dd4bf', data: mfi(c, 14) }],
    needsVolume: true,
  },
  aroon: {
    label: 'Aroon 25', levels: [70, 30], range: [0, 100],
    build: (c) => {
      const a = aroon(c, 25);
      return [{ id: 'up', name: 'Up', color: GREEN, data: a.up }, { id: 'down', name: 'Down', color: RED, data: a.down }];
    },
  },
};

const fmt = (v) => (v == null ? '—' : Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(2));

export default function IndicatorPane({ id, candles, mainChart, hoverTime, onHoverTime, onClose, height = 120 }) {
  const def = PANE_DEFS[id];
  const [el, setEl] = useState(null);
  const [chart, setChart] = useState(null);   // state, not a ref: the effects below must re-run when it appears
  const seriesRef = useRef([]);          // [{ spec, series }]
  const [specs, setSpecs] = useState([]);

  // compute whenever the candles change
  useEffect(() => { setSpecs(def && candles?.length ? def.build(candles) : []); }, [def, candles]);

  // create the strip's chart once its container exists
  useEffect(() => {
    if (!el) return undefined;
    const chart = createChart(el, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#94a3b8', fontSize: 10, attributionLogo: false },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155', minimumWidth: 72, scaleMargins: { top: 0.12, bottom: 0.12 } },
      timeScale: { borderColor: '#334155', visible: false },
      handleScroll: { mouseWheel: true, pressedMouseMove: true },
      width: el.clientWidth, height,
    });
    setChart(chart);
    const ro = new ResizeObserver((entries) => { const w = entries[0]?.contentRect.width; if (w > 0) chart.applyOptions({ width: w }); });
    ro.observe(el);
    return () => { ro.disconnect(); setChart(null); chart.remove(); seriesRef.current = []; };
  }, [el, height]);

  // (re)build the series and their data
  useEffect(() => {
    if (!chart || !candles?.length) return;
    seriesRef.current.forEach(({ series }) => chart.removeSeries(series));
    seriesRef.current = specs.map((spec, idx) => {
      const series = spec.kind === 'hist'
        ? chart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false, priceScaleId: 'right' })
        : chart.addLineSeries({ color: spec.color, lineWidth: spec.width || 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      series.setData(spec.data.map((v, i) => {
        if (v == null) return { time: candles[i].time };
        return spec.kind === 'hist' ? { time: candles[i].time, value: v, color: v >= 0 ? '#34d39988' : '#f8717188' } : { time: candles[i].time, value: v };
      }));
      if (idx === 0 && def?.levels) {
        def.levels.forEach((price) => series.createPriceLine({ price, color: '#475569', lineWidth: 1, lineStyle: 2, axisLabelVisible: false }));
      }
      return { spec, series };
    });
    if (def?.range) {   // fixed 0-100 scale for bounded oscillators, via an invisible pair of anchor points
      const first = seriesRef.current.find((s) => s.spec.kind !== 'hist')?.series;
      if (first) first.applyOptions({ autoscaleInfoProvider: () => ({ priceRange: { minValue: def.range[0], maxValue: def.range[1] } }) });
    }
    const r = mainChart?.timeScale().getVisibleLogicalRange();
    if (r) chart.timeScale().setVisibleLogicalRange(r);
  }, [chart, specs, candles, def, mainChart]);

  // keep the time scale in lock-step with the main chart (both directions, guarded against echo)
  useEffect(() => {
    if (!chart || !mainChart) return undefined;
    let lock = false;
    const fromMain = (r) => { if (lock || !r) return; lock = true; try { chart.timeScale().setVisibleLogicalRange(r); } finally { lock = false; } };
    const fromPane = (r) => { if (lock || !r) return; lock = true; try { mainChart.timeScale().setVisibleLogicalRange(r); } finally { lock = false; } };
    mainChart.timeScale().subscribeVisibleLogicalRangeChange(fromMain);
    chart.timeScale().subscribeVisibleLogicalRangeChange(fromPane);
    const r = mainChart.timeScale().getVisibleLogicalRange();
    if (r) chart.timeScale().setVisibleLogicalRange(r);
    const onMove = (param) => onHoverTime && onHoverTime(param.time || null);
    chart.subscribeCrosshairMove(onMove);
    return () => {
      try { mainChart.timeScale().unsubscribeVisibleLogicalRangeChange(fromMain); } catch { /* chart already disposed */ }
      try { chart.timeScale().unsubscribeVisibleLogicalRangeChange(fromPane); chart.unsubscribeCrosshairMove(onMove); } catch { /* disposed */ }
    };
  }, [chart, mainChart]);

  if (!def) return null;
  const idxByTime = hoverTime != null && candles ? candles.findIndex((c) => c.time === hoverTime) : -1;
  const at = idxByTime >= 0 ? idxByTime : (candles?.length || 1) - 1;
  const noVolume = def.needsVolume && candles && !candles.some((c) => c.volume > 0);

  return (
    <div className="mt-1 rounded-lg border border-slate-800 bg-slate-950/40">
      <div className="flex items-center justify-between px-2 pt-1 text-[10px]">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-slate-300 font-semibold">{def.label}</span>
          {!noVolume && specs.map((sp) => (
            <span key={sp.id} className="text-slate-500">{sp.name} <span style={{ color: sp.color || SLATE }} className="font-medium">{fmt(sp.data[at])}</span></span>
          ))}
          {noVolume && <span className="text-amber-500/80">needs volume — this instrument has none</span>}
        </div>
        <button onClick={onClose} title="Remove this indicator" className="text-slate-600 hover:text-slate-300 px-1">✕</button>
      </div>
      <div ref={setEl} className="w-full" style={{ height }} />
    </div>
  );
}
