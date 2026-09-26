/**
 * frontend/src/utils/indianNumberFormat.test.js
 *
 * Sep 26 2026: no JS test framework (vitest/jest) exists anywhere in
 * this project yet -- adding one is a bigger decision than "test one
 * formatter," so this is a standalone, dependency-free test file.
 * Run directly with: node src/utils/indianNumberFormat.test.js
 *
 * Every case here is either a literal example from the formatting
 * spec, a real value pulled from your actual GAIL screenshots, or an
 * explicit edge case the spec called out (negatives, nulls, decimal
 * precision, chart-axis consistency).
 */
import {
  formatIndianCurrency, toIndianUnit, pickSeriesUnit, formatAxisTick,
  formatPercent, formatRatio,
} from './indianNumberFormat.js';

let passed = 0, failed = 0;

function assertEqual(actual, expected, label) {
  if (actual === expected) {
    passed++;
  } else {
    failed++;
    console.error(`FAIL: ${label}\n  expected: ${JSON.stringify(expected)}\n  actual:   ${JSON.stringify(actual)}`);
  }
}

function assertContains(actual, substr, label) {
  if (String(actual).includes(substr)) {
    passed++;
  } else {
    failed++;
    console.error(`FAIL: ${label}\n  expected "${actual}" to contain "${substr}"`);
  }
}

// --- Crore conversion (spec's own examples, decimal-trimmed per the spec's own "remove trailing zeros" rule) ---
assertEqual(formatIndianCurrency(12000000000), '₹1,200 Cr', 'Crore: 1200 Cr example');
assertEqual(formatIndianCurrency(250011400000), '₹25,001.14 Cr', 'Crore: 25001.14 Cr example');
assertEqual(formatIndianCurrency(120000000), '₹12 Cr', 'Crore: 12 Cr example');
assertEqual(formatIndianCurrency(10000000), '₹1 Cr', 'Crore: exactly 1 Cr boundary');

// --- Lakh conversion ---
assertEqual(formatIndianCurrency(5000000), '₹50 L', 'Lakh: 50 L example');
assertEqual(formatIndianCurrency(1250000), '₹12.5 L', 'Lakh: 12.5 L example (trailing zero trimmed per spec rule)');
assertEqual(formatIndianCurrency(100000), '₹1 L', 'Lakh: exactly 1 lakh boundary');
assertEqual(formatIndianCurrency(99999), '₹99,999', 'Just under 1 lakh stays in plain rupees with Indian grouping');

// --- Real values from your actual GAIL screenshots ---
assertEqual(formatIndianCurrency(1420943000000), '₹1,42,094.3 Cr', 'Real GAIL revenue');
assertEqual(formatIndianCurrency(75815200000), '₹7,581.52 Cr', 'Real GAIL PAT');
assertEqual(formatIndianCurrency(1559185200000), '₹1,55,918.52 Cr', 'Real GAIL segment value (the one that exposed the reconciliation bug)');

// --- Negative values -- sign must stay correct, not silently dropped ---
assertEqual(formatIndianCurrency(-50000000), '-₹5 Cr', 'Negative crore value');
assertEqual(formatIndianCurrency(-1250000), '-₹12.5 L', 'Negative lakh value');
assertContains(toIndianUnit(-50000000).value, '-5', 'toIndianUnit preserves negative sign');

// --- Null/undefined/NaN -- must show "—", never fabricate a number ---
assertEqual(formatIndianCurrency(null), '—', 'null shows em-dash, not a fabricated number');
assertEqual(formatIndianCurrency(undefined), '—', 'undefined shows em-dash');
assertEqual(formatIndianCurrency(NaN), '—', 'NaN shows em-dash');
assertEqual(formatIndianCurrency('not a number'), '—', 'non-numeric string shows em-dash, not silently parsed as 0');

// --- Ratios/percentages must NEVER get Cr/L suffix (spec section 3 explicit) ---
assertEqual(formatPercent(8.49), '+8.49%', 'ROE stays a plain percentage');
assertEqual(formatRatio(0.22), '0.22x', 'Debt/Equity stays a plain ratio');
assertEqual(formatRatio(11.49), '11.49x', 'P/E stays a plain ratio');
assertEqual(formatRatio(1.27), '1.27x', 'P/B stays a plain ratio');

// --- Chart axis: one series must resolve to ONE consistent unit, never mixed Cr/L on the same axis ---
{
  const series = [1420943000000, 1200000000000, null, 1500000000000];
  const unit = pickSeriesUnit(series);
  assertEqual(unit.unit, 'Cr', 'Series unit picked as Cr for crore-scale values');
  assertEqual(formatAxisTick(1420943000000, unit), '1,42,094Cr', 'Axis tick uses the same consistent Indian-grouped formatting as everywhere else (spec section 4: same rules across cards/charts/tooltips)');
  assertEqual(formatAxisTick(null, unit), '', 'Null value in a series produces an empty tick, not "NaN" or a crash');
}
{
  // A series that's entirely lakh-scale should pick L, not Cr
  const smallSeries = [5000000, 6000000, 4500000];
  const unit = pickSeriesUnit(smallSeries);
  assertEqual(unit.unit, 'L', 'Series unit picked as L for lakh-scale values');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
