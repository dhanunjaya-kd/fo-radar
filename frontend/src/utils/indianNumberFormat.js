/**
 * frontend/src/utils/indianNumberFormat.js
 *
 * Sep 26 2026: built against a real, visible bug -- raw unformatted
 * numbers (e.g. 1420943000000) were wide enough to get clipped on
 * chart y-axes, rendering as unreadable truncated strings like
 * "0000000000". This isn't cosmetic -- it's why the charts looked
 * wrong even when the underlying data was fine.
 *
 * Pure formatting only. Never touches the raw numeric value used for
 * calculations -- these functions take a number, return a display
 * STRING, and nothing here writes back to any data source.
 */

/**
 * Converts a raw INR value into a human Indian-unit string.
 * >= 1 crore (1e7)  -> "X,XXX.XX Cr"
 * >= 1 lakh (1e5)    -> "X,XXX.XX L"
 * < 1 lakh           -> plain Indian-grouped rupees
 * null/undefined/NaN -> "—" (never fabricates a number for a missing value)
 */
export function formatIndianCurrency(value, { decimals = 2, prefix = '₹' } = {}) {
  if (value == null) return '—';
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (!Number.isFinite(num)) return '—';

  const isNegative = num < 0;
  const abs = Math.abs(num);
  const sign = isNegative ? '-' : '';

  if (abs >= 1e7) {
    return `${sign}${prefix}${trimTrailingZeros(abs / 1e7, decimals)} Cr`;
  }
  if (abs >= 1e5) {
    return `${sign}${prefix}${trimTrailingZeros(abs / 1e5, decimals)} L`;
  }
  return `${sign}${prefix}${formatIndianGrouping(abs, decimals)}`;
}

/**
 * Same conversion, but returns {value, unit} separately -- for chart
 * axes/tooltips that want to control layout themselves rather than
 * consume a pre-built string.
 */
export function toIndianUnit(value, decimals = 2) {
  if (value == null) return { value: null, unit: '' };
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (!Number.isFinite(num)) return { value: null, unit: '' };

  const isNegative = num < 0;
  const abs = Math.abs(num);
  const sign = isNegative ? -1 : 1;

  if (abs >= 1e7) return { value: sign * round(abs / 1e7, decimals), unit: 'Cr' };
  if (abs >= 1e5) return { value: sign * round(abs / 1e5, decimals), unit: 'L' };
  return { value: sign * round(abs, decimals), unit: '' };
}

/** For a whole SERIES of chart values, picks ONE consistent unit (the
 * largest value's natural unit) so every point on one chart/axis uses
 * the same Cr-or-L scale -- never mixed units across one axis. */
export function pickSeriesUnit(values) {
  const finite = (values || []).filter(v => v != null && Number.isFinite(typeof v === 'string' ? parseFloat(v) : v));
  if (!finite.length) return { divisor: 1, unit: '' };
  const maxAbs = Math.max(...finite.map(v => Math.abs(typeof v === 'string' ? parseFloat(v) : v)));
  if (maxAbs >= 1e7) return { divisor: 1e7, unit: 'Cr' };
  if (maxAbs >= 1e5) return { divisor: 1e5, unit: 'L' };
  return { divisor: 1, unit: '' };
}

/** Chart axis tick formatter -- given a raw value and a series' chosen
 * {divisor, unit} (from pickSeriesUnit), returns a short axis label. */
export function formatAxisTick(rawValue, { divisor, unit }) {
  if (rawValue == null || !Number.isFinite(rawValue)) return '';
  const scaled = rawValue / divisor;
  const label = trimTrailingZeros(scaled, scaled >= 100 ? 0 : 1);
  return unit ? `${label}${unit}` : label;
}

/** Tooltip formatter -- full precision-appropriate string with the label, e.g. "Revenue: ₹1,42,094.30 Cr" */
export function formatTooltipValue(rawValue, label) {
  return `${label}: ${formatIndianCurrency(rawValue)}`;
}

// ---- Ratios/percentages/per-share -- explicitly NOT run through Cr/L conversion ----
export function formatPercent(value, decimals = 2) {
  if (value == null) return '—';
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (!Number.isFinite(num)) return '—';
  return `${num > 0 ? '+' : ''}${num.toFixed(decimals)}%`;
}

export function formatRatio(value, decimals = 2, suffix = 'x') {
  if (value == null) return '—';
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (!Number.isFinite(num)) return '—';
  return `${num.toFixed(decimals)}${suffix}`;
}

// ---- internals ----

function round(num, decimals) {
  const factor = 10 ** decimals;
  return Math.round(num * factor) / factor;
}

function trimTrailingZeros(num, maxDecimals) {
  const rounded = round(num, maxDecimals);
  let str = rounded.toFixed(maxDecimals);
  if (str.includes('.')) {
    str = str.replace(/0+$/, '').replace(/\.$/, '');
  }
  // Sep 26 2026 fix: the spec's own examples show Indian comma
  // grouping WITHIN the Cr/L value too (e.g. "₹25,001.14 Cr", not
  // "₹25001.14 Cr") -- confirmed missing by testing against the
  // spec's exact examples, not assumed. Apply the same grouping used
  // for sub-lakh values here too.
  const [intPart, decPart] = str.split('.');
  const groupedInt = groupIndianDigits(intPart);
  return decPart ? `${groupedInt}.${decPart}` : groupedInt;
}

function groupIndianDigits(intStr) {
  const negative = intStr.startsWith('-');
  let digits = negative ? intStr.slice(1) : intStr;
  let result = '';
  if (digits.length > 3) {
    result = ',' + digits.slice(-3);
    digits = digits.slice(0, -3);
    while (digits.length > 2) {
      result = ',' + digits.slice(-2) + result;
      digits = digits.slice(0, -2);
    }
  }
  const grouped = digits + result;
  return negative ? `-${grouped}` : grouped;
}

/** Indian digit grouping (2,2,2,...,3) for values under 1 lakh, e.g. 45230 -> "45,230" */
function formatIndianGrouping(num, decimals) {
  const rounded = round(num, decimals);
  const parts = rounded.toFixed(decimals).split('.');
  const grouped = groupIndianDigits(parts[0]);
  const decPart = parts[1];
  const trimmedDec = decPart && decimals > 0 ? decPart.replace(/0+$/, '') : '';
  return trimmedDec ? `${grouped}.${trimmedDec}` : grouped;
}
