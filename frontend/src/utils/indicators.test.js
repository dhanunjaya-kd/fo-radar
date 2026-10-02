/**
 * frontend/src/utils/indicators.test.js
 *
 * Standalone, dependency-free (same convention as indianNumberFormat.test.js):  node src/utils/indicators.test.js
 *
 * Two kinds of check:
 *  1. REFERENCE values from TA-Lib (the industry-standard C library) on a frozen synthetic series --
 *     fixtures/indicators_talib_reference.json. Tolerance is 1e-6 (RSI/BB/CCI/MFI/Aroon/PSAR/StochRSI/MACD), 5e-3 for
 *     ADX/DI (TA-Lib seeds its first smoothed value slightly differently; agreement is ~1e-5 relative).
 *     MACD and ADX are compared from bar 130 on, once their recursive smoothing has converged.
 *  2. Hand-checkable properties (constant series, straight trends, warm-up nulls, gaps, no volume).
 */
import fs from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';
import * as I from './indicators.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const fx = JSON.parse(fs.readFileSync(path.join(here, 'fixtures', 'indicators_talib_reference.json'), 'utf8'));
let passed = 0, failed = 0;
const ok = (cond, name, extra = '') => { if (cond) passed++; else { failed++; console.log(`FAIL: ${name} ${extra}`); } };
const near = (a, b, tol) => a != null && b != null && Math.abs(a - b) <= tol;

// ---- 1. TA-Lib reference ----
const candles = fx.candles;
const m = I.macd(candles), b = I.bollinger(candles), a = I.adx(candles), ar = I.aroon(candles, 25), sr = I.stochRsi(candles);
const raw = (() => { const r = I.rsi(candles, 14); return r.map((_, i) => { if (r[i] == null || i < 13) return null; let lo = Infinity, hi = -Infinity; for (let j = i - 13; j <= i; j++) { if (r[j] == null) return null; lo = Math.min(lo, r[j]); hi = Math.max(hi, r[j]); } return hi === lo ? 0 : 100 * (r[i] - lo) / (hi - lo); }); })();
const mine = {
  rsi: I.rsi(candles, 14), macd: m.macd, signal: m.signal, hist: m.hist, bb_u: b.upper, bb_m: b.mid, bb_l: b.lower,
  adx: a.adx, pdi: a.plusDI, mdi: a.minusDI, cci: I.cci(candles, 20), mfi: I.mfi(candles, 14),
  aroon_up: ar.up, aroon_dn: ar.down, psar: I.psar(candles), stochrsi_raw: raw, stochrsi_k3: sr.k,
};
const SLOW = new Set(['macd', 'signal', 'hist', 'adx', 'pdi', 'mdi']);   // recursive smoothing: compare once converged
for (const [name, expected] of Object.entries(fx.ref)) {
  const tol = SLOW.has(name) && ['adx', 'pdi', 'mdi'].includes(name) ? 5e-3 : 1e-6;
  fx.indices.forEach((idx, n) => {
    if (expected[n] == null || (SLOW.has(name) && idx < 130)) return;
    ok(near(mine[name][idx], expected[n], tol), `${name}[${idx}] vs TA-Lib`, `mine=${mine[name][idx]} ref=${expected[n]}`);
  });
}

// ---- 2. properties ----
const mk = (closes, spread = 1, vol = 100) => closes.map((c, i) => ({ time: i, open: c, high: c + spread, low: c - spread, close: c, volume: vol }));
const flat = mk(new Array(60).fill(100));
const up = mk(Array.from({ length: 80 }, (_, i) => 100 + i));
const down = mk(Array.from({ length: 80 }, (_, i) => 200 - i));

// SMA / EMA
ok(JSON.stringify(I.sma([1, 2, 3, 4, 5], 3)) === JSON.stringify([null, null, 2, 3, 4]), 'sma basic');
ok(JSON.stringify(I.sma([1, 2, null, 4, 5, 6], 2)) === JSON.stringify([null, 1.5, null, null, 4.5, 5.5]), 'sma gap restarts the window');
const e = I.ema([2, 4, 6, 8, 10], 3);
ok(e[0] == null && e[1] == null && e[2] === 4 && near(e[3], 6, 1e-12) && near(e[4], 8, 1e-12), 'ema seeded by SMA', JSON.stringify(e));

// warm-up is null, never invented
ok(I.rsi(up, 14).slice(0, 14).every((v) => v === null), 'rsi warm-up is null');
ok(I.macd(up).macd.slice(0, 25).every((v) => v === null) && I.macd(up).macd[25] != null, 'macd warm-up is null');
ok(I.bollinger(up).upper.slice(0, 19).every((v) => v === null), 'bollinger warm-up is null');
ok(I.adx(mk([1, 2, 3, 4, 5])).adx.every((v) => v === null), 'adx too short -> all null');
ok(I.rsi(mk([1, 2, 3]), 14).every((v) => v === null), 'rsi too short -> all null');

// RSI extremes
ok(I.rsi(up, 14).at(-1) === 100, 'rsi of a straight rise is 100');
ok(I.rsi(down, 14).at(-1) === 0, 'rsi of a straight fall is 0');
ok(I.rsi(flat, 14).at(-1) === 50, 'rsi of a flat series is 50');

// Bollinger
const bf = I.bollinger(flat);
ok(bf.upper.at(-1) === 100 && bf.lower.at(-1) === 100, 'bollinger collapses on a flat series');
const bu = I.bollinger(up);
ok(bu.upper.at(-1) > bu.mid.at(-1) && bu.mid.at(-1) > bu.lower.at(-1), 'bollinger bands ordered');

// MACD
ok(Math.abs(I.macd(flat).macd.at(-1)) < 1e-9, 'macd of a flat series is 0');
ok(I.macd(up).macd.at(-1) > 0 && I.macd(down).macd.at(-1) < 0, 'macd sign follows trend');

// ADX / DI
ok(I.adx(up).adx.at(-1) > 40, 'adx is high in a clean trend', String(I.adx(up).adx.at(-1)));
ok(I.adx(up).plusDI.at(-1) > I.adx(up).minusDI.at(-1), '+DI > -DI in an uptrend');
ok(I.adx(down).minusDI.at(-1) > I.adx(down).plusDI.at(-1), '-DI > +DI in a downtrend');
const chop = mk(Array.from({ length: 120 }, (_, i) => 100 + (i % 2 ? 1 : -1)));
ok(I.adx(chop).adx.at(-1) < 15, 'adx is low in chop', String(I.adx(chop).adx.at(-1)));

// Stoch RSI range
const sw = mk(Array.from({ length: 150 }, (_, i) => 100 + 10 * Math.sin(i / 5)));
const skv = I.stochRsi(sw).k.filter((v) => v != null);
ok(skv.length > 50 && skv.every((v) => v >= -1e-9 && v <= 100 + 1e-9), 'stoch rsi stays within 0..100');

// CCI
ok(I.cci(flat).at(-1) === 0, 'cci of a flat series is 0');
ok(I.cci(up).at(-1) > 100, 'cci is strongly positive in a steady rise');

// MFI
ok(I.mfi(up, 14).at(-1) === 100, 'mfi of a straight rise is 100');
ok(I.mfi(mk(Array.from({ length: 40 }, (_, i) => 100 + i), 1, 0), 14).every((v) => v === null), 'mfi is null when the feed has no volume (indices)');

// Aroon
const ar2 = I.aroon(up, 25);
ok(ar2.up.at(-1) === 100 && ar2.down.at(-1) === 0, 'aroon in a straight rise: up 100, down 0');
ok(I.aroon(down, 25).down.at(-1) === 100, 'aroon in a straight fall: down 100');

// PSAR
const ps = I.psar(up);
ok(ps.slice(1).every((v, i) => v != null && v < up[i + 1].low + 1e-9), 'psar sits below price in an uptrend');
const turn = mk([...Array.from({ length: 40 }, (_, i) => 100 + i), ...Array.from({ length: 40 }, (_, i) => 140 - i * 1.5)]);
const pt = I.psar(turn);
ok(pt[30] < turn[30].low && pt.at(-1) > turn.at(-1).high, 'psar flips from below to above price after a reversal');

console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
