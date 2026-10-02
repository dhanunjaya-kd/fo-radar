/**
 * frontend/src/utils/indicators.js
 *
 * Oct 2 2026: technical indicators for the Fundamental Research chart, computed client-side from the
 * candles the chart already has (so they work on every timeframe, 5m to 1W, with no new backend call).
 *
 * Every function takes `candles` = [{ time, open, high, low, close, volume }, ...] oldest first and
 * returns arrays ALIGNED to it, with null wherever there isn't enough history yet -- never a made-up
 * warm-up value. Definitions are the standard ones (Wilder smoothing for RSI/ADX, population standard
 * deviation for Bollinger Bands as TradingView does, 0.015 constant for CCI).
 * Cross-checked against the Python `ta` library in indicators.test.js's header notes.
 */

const nulls = (n) => new Array(n).fill(null);

export function sma(values, period) {
  const out = nulls(values.length);
  let sum = 0, count = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null) { sum = 0; count = 0; continue; }   // a gap restarts the window
    sum += v; count++;
    if (count > period) { sum -= values[i - period]; count = period; }
    if (count === period) out[i] = sum / period;
  }
  return out;
}

/** EMA seeded with the SMA of the first `period` non-null values (the textbook definition). */
export function ema(values, period) {
  const out = nulls(values.length);
  const k = 2 / (period + 1);
  let seeded = false, prev = 0, sum = 0, count = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null) continue;
    if (!seeded) {
      sum += v; count++;
      if (count === period) { prev = sum / period; out[i] = prev; seeded = true; }
    } else {
      prev = (v - prev) * k + prev;
      out[i] = prev;
    }
  }
  return out;
}

export function bollinger(candles, period = 20, mult = 2) {
  const closes = candles.map((c) => c.close);
  const mid = sma(closes, period);
  const upper = nulls(closes.length), lower = nulls(closes.length);
  for (let i = period - 1; i < closes.length; i++) {
    if (mid[i] == null) continue;
    let v = 0;
    for (let j = i - period + 1; j <= i; j++) v += (closes[j] - mid[i]) ** 2;
    const sd = Math.sqrt(v / period);                  // population SD
    upper[i] = mid[i] + mult * sd;
    lower[i] = mid[i] - mult * sd;
  }
  return { upper, mid, lower };
}

/** Wilder's RSI. */
export function rsi(candles, period = 14) {
  const closes = candles.map((c) => c.close);
  const out = nulls(closes.length);
  if (closes.length <= period) return out;
  let gain = 0, loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d >= 0) gain += d; else loss -= d;
  }
  let avgGain = gain / period, avgLoss = loss / period;
  const toRsi = () => (avgLoss === 0 ? (avgGain === 0 ? 50 : 100) : 100 - 100 / (1 + avgGain / avgLoss));
  out[period] = toRsi();
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    avgGain = (avgGain * (period - 1) + (d > 0 ? d : 0)) / period;
    avgLoss = (avgLoss * (period - 1) + (d < 0 ? -d : 0)) / period;
    out[i] = toRsi();
  }
  return out;
}

export function macd(candles, fast = 12, slow = 26, signalPeriod = 9) {
  const closes = candles.map((c) => c.close);
  const f = ema(closes, fast), s = ema(closes, slow);
  const line = closes.map((_, i) => (f[i] != null && s[i] != null ? f[i] - s[i] : null));
  const signal = ema(line, signalPeriod);
  const hist = line.map((v, i) => (v != null && signal[i] != null ? v - signal[i] : null));
  return { macd: line, signal, hist };
}

/** Wilder's ADX with +DI / -DI. */
export function adx(candles, period = 14) {
  const n = candles.length;
  const adxOut = nulls(n), plusDI = nulls(n), minusDI = nulls(n);
  if (n <= period * 2) return { adx: adxOut, plusDI, minusDI };
  const tr = nulls(n), pdm = nulls(n), mdm = nulls(n);
  for (let i = 1; i < n; i++) {
    const up = candles[i].high - candles[i - 1].high;
    const down = candles[i - 1].low - candles[i].low;
    pdm[i] = up > down && up > 0 ? up : 0;
    mdm[i] = down > up && down > 0 ? down : 0;
    tr[i] = Math.max(candles[i].high - candles[i].low, Math.abs(candles[i].high - candles[i - 1].close), Math.abs(candles[i].low - candles[i - 1].close));
  }
  let sTR = 0, sP = 0, sM = 0;
  for (let i = 1; i <= period; i++) { sTR += tr[i]; sP += pdm[i]; sM += mdm[i]; }
  const dx = nulls(n);
  const setDI = (i) => {
    plusDI[i] = sTR === 0 ? 0 : (100 * sP) / sTR;
    minusDI[i] = sTR === 0 ? 0 : (100 * sM) / sTR;
    const tot = plusDI[i] + minusDI[i];
    dx[i] = tot === 0 ? 0 : (100 * Math.abs(plusDI[i] - minusDI[i])) / tot;
  };
  setDI(period);
  for (let i = period + 1; i < n; i++) {
    sTR = sTR - sTR / period + tr[i];
    sP = sP - sP / period + pdm[i];
    sM = sM - sM / period + mdm[i];
    setDI(i);
  }
  let first = 0;
  for (let i = period; i < period * 2; i++) first += dx[i];
  let prev = first / period;
  adxOut[period * 2 - 1] = prev;
  for (let i = period * 2; i < n; i++) {
    prev = (prev * (period - 1) + dx[i]) / period;
    adxOut[i] = prev;
  }
  return { adx: adxOut, plusDI, minusDI };
}

/** Stochastic RSI: %K and %D on a 0-100 scale. */
export function stochRsi(candles, rsiPeriod = 14, stochPeriod = 14, kSmooth = 3, dSmooth = 3) {
  const r = rsi(candles, rsiPeriod);
  const raw = nulls(r.length);
  for (let i = 0; i < r.length; i++) {
    if (r[i] == null || i < stochPeriod - 1) continue;
    let lo = Infinity, hi = -Infinity, ok = true;
    for (let j = i - stochPeriod + 1; j <= i; j++) {
      if (r[j] == null) { ok = false; break; }
      lo = Math.min(lo, r[j]); hi = Math.max(hi, r[j]);
    }
    if (ok) raw[i] = hi === lo ? 0 : (100 * (r[i] - lo)) / (hi - lo);
  }
  const k = sma(raw, kSmooth);
  const d = sma(k, dSmooth);
  return { k, d };
}

export function cci(candles, period = 20) {
  const tp = candles.map((c) => (c.high + c.low + c.close) / 3);
  const mean = sma(tp, period);
  const out = nulls(tp.length);
  for (let i = period - 1; i < tp.length; i++) {
    if (mean[i] == null) continue;
    let dev = 0;
    for (let j = i - period + 1; j <= i; j++) dev += Math.abs(tp[j] - mean[i]);
    dev /= period;
    out[i] = dev === 0 ? 0 : (tp[i] - mean[i]) / (0.015 * dev);
  }
  return out;
}

/** Money Flow Index -- RSI-like, but volume-weighted. Null when the feed has no volume (indices). */
export function mfi(candles, period = 14) {
  const n = candles.length;
  const out = nulls(n);
  if (!candles.some((c) => c.volume > 0)) return out;
  const tp = candles.map((c) => (c.high + c.low + c.close) / 3);
  const pos = nulls(n), neg = nulls(n);
  for (let i = 1; i < n; i++) {
    const flow = tp[i] * (candles[i].volume || 0);
    pos[i] = tp[i] > tp[i - 1] ? flow : 0;
    neg[i] = tp[i] < tp[i - 1] ? flow : 0;
  }
  for (let i = period; i < n; i++) {
    let p = 0, q = 0;
    for (let j = i - period + 1; j <= i; j++) { p += pos[j]; q += neg[j]; }
    out[i] = q === 0 ? (p === 0 ? 50 : 100) : 100 - 100 / (1 + p / q);
  }
  return out;
}

export function aroon(candles, period = 25) {
  const n = candles.length;
  const up = nulls(n), down = nulls(n);
  for (let i = period; i < n; i++) {
    let hiIdx = i - period, loIdx = i - period;
    for (let j = i - period; j <= i; j++) {
      if (candles[j].high >= candles[hiIdx].high) hiIdx = j;    // most recent extreme wins ties
      if (candles[j].low <= candles[loIdx].low) loIdx = j;
    }
    up[i] = (100 * (period - (i - hiIdx))) / period;
    down[i] = (100 * (period - (i - loIdx))) / period;
  }
  return { up, down };
}

/** Parabolic SAR (Wilder): step 0.02, max 0.2. Returns the SAR value per bar. */
export function psar(candles, step = 0.02, maxStep = 0.2) {
  const n = candles.length;
  const out = nulls(n);
  if (n < 3) return out;
  let rising = candles[1].close >= candles[0].close;
  let sar = rising ? candles[0].low : candles[0].high;
  let ep = rising ? candles[1].high : candles[1].low;
  let af = step;
  out[1] = sar;
  for (let i = 2; i < n; i++) {
    sar = sar + af * (ep - sar);
    if (rising) {
      sar = Math.min(sar, candles[i - 1].low, candles[i - 2].low);
      if (candles[i].low <= sar) {                      // reversal to a downtrend: SAR jumps to the old extreme,
        rising = false;                                 // but never inside the last two bars' highs
        sar = Math.max(ep, candles[i - 1].high, candles[i].high);
        ep = candles[i].low; af = step;
      } else if (candles[i].high > ep) { ep = candles[i].high; af = Math.min(af + step, maxStep); }
    } else {
      sar = Math.max(sar, candles[i - 1].high, candles[i - 2].high);
      if (candles[i].high >= sar) {                     // reversal to an uptrend
        rising = true;
        sar = Math.min(ep, candles[i - 1].low, candles[i].low);
        ep = candles[i].high; af = step;
      } else if (candles[i].low < ep) { ep = candles[i].low; af = Math.min(af + step, maxStep); }
    }
    out[i] = sar;
  }
  return out;
}
