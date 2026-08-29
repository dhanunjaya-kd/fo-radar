import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Aug 29 2026: LIVE vs CLOSED · LAST labeling, per the PDF's data-state
// table. Logic copied verbatim from MarketBanner.jsx (11 status-logic
// tests + 3 timezone tests already passed there), not re-derived.
// This component shows the LAST LOGGED SNAPSHOT, not a direct live
// quote -- while the market's open, new snapshots log every ~60s, so
// that value is effectively live; once closed, it's the last known
// value from before close. Same honest limitation as everywhere else
// this logic is used: weekday + time-of-day only, no NSE holiday
// calendar wired in anywhere in this project.
const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MARKET_OPEN_MIN = 9 * 60 + 15;
const MARKET_CLOSE_MIN = 15 * 60 + 30;

function getIstDayAndMinutes(date) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Kolkata',
    weekday: 'short', hour: 'numeric', minute: 'numeric', hour12: false,
  }).formatToParts(date);
  const get = (type) => parts.find(p => p.type === type)?.value;
  const weekdayMap = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  const day = weekdayMap[get('weekday')];
  let hour = parseInt(get('hour'), 10);
  if (hour === 24) hour = 0;
  const minute = parseInt(get('minute'), 10);
  return { day, totalMinutes: hour * 60 + minute };
}

function computeMarketStatus(day, totalMinutes) {
  const isWeekday = day >= 1 && day <= 5;
  const isWithinHours = totalMinutes >= MARKET_OPEN_MIN && totalMinutes < MARKET_CLOSE_MIN;
  const isOpen = isWeekday && isWithinHours;

  if (isOpen) {
    return { isOpen: true, label: 'Market Open', nextEvent: 'Closes at 3:30 PM' };
  }

  let daysUntilNextOpen = 0;
  let candidateDay = day;

  if (isWeekday && totalMinutes < MARKET_OPEN_MIN) {
    daysUntilNextOpen = 0;
  } else {
    do {
      candidateDay = (candidateDay + 1) % 7;
      daysUntilNextOpen++;
    } while (candidateDay === 0 || candidateDay === 6);
  }

  const dayLabel = daysUntilNextOpen === 0 ? 'today' : (daysUntilNextOpen === 1 ? 'tomorrow' : `on ${DAY_NAMES[candidateDay]}`);
  return { isOpen: false, label: 'Market Closed', nextEvent: `Opens 9:15 AM ${dayLabel}` };
}

// Aug 28 2026: all three pieces here (date selection, downsampling,
// coordinate transform) tested independently before being wired
// together -- test_chart_range_logic.js and test_chart_coordinates.js.
const RANGE_PAST_DAYS = { '1D': 0, '5D': 4, '1M': 21, '3M': 63 };
const RANGES = ['1D', '5D', '1M', '3M'];

function selectDatesForRange(availableDates, range) {
  const pastDaysNeeded = RANGE_PAST_DAYS[range] ?? 0;
  const sorted = [...availableDates].sort((a, b) => b.localeCompare(a));
  return sorted.slice(0, pastDaysNeeded);
}

function downsample(points, maxPoints = 500) {
  if (points.length <= maxPoints) return points;
  const step = Math.ceil(points.length / maxPoints);
  const result = [];
  for (let i = 0; i < points.length; i += step) result.push(points[i]);
  if (result[result.length - 1] !== points[points.length - 1]) {
    result.push(points[points.length - 1]);
  }
  return result;
}

function buildChartPath(values, width, height, padding = 4) {
  const clean = values.filter(v => v != null && !isNaN(v));
  if (clean.length < 2) return null;
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const range = max - min || 1;
  const usableWidth = width - padding * 2;
  const usableHeight = height - padding * 2;
  const stepX = usableWidth / (clean.length - 1);
  const coords = clean.map((v, i) => ({
    x: padding + i * stepX,
    y: padding + usableHeight - ((v - min) / range) * usableHeight,
  }));
  const path = coords.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  return { path, min, max, coords };
}

const DISPLAY_NAME = { NIFTY: 'NIFTY', BANKNIFTY: 'BANKNIFTY' };

export default function IndexPriceChart({ indexName }) {
  const [range, setRange] = useState('1D');
  const [marketStatus, setMarketStatus] = useState(null);
  useEffect(() => {
    const update = () => {
      const { day, totalMinutes } = getIstDayAndMinutes(new Date());
      setMarketStatus(computeMarketStatus(day, totalMinutes));
    };
    update();
    const interval = setInterval(update, 30000);
    return () => clearInterval(interval);
  }, []);
  const [points, setPoints] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const load = async () => {
      try {
        const datesRes = await fetch(`${API_BASE}/api/index-tracker/${indexName}/dates/`);
        const datesJson = await datesRes.json();
        const pastDates = selectDatesForRange(datesJson.dates || [], range);

        // Fetch today + whichever past dates the range needs, in
        // parallel. Today's data is always included regardless of
        // range (it's the most current, always-relevant tail of the
        // chart).
        const urls = [
          `${API_BASE}/api/index-tracker/${indexName}/`,
          ...pastDates.map(d => `${API_BASE}/api/index-tracker/${indexName}/?date=${d}`),
        ];
        const responses = await Promise.all(urls.map(u => fetch(u).then(r => r.json()).catch(() => ({ snapshots: [] }))));

        // Each day's snapshots come back most-recent-first; today's
        // response is index 0, past dates follow in most-recent-past-
        // first order (matching pastDates' own order). To build one
        // continuous chronological series: reverse EACH day's rows to
        // oldest-first, then concatenate OLDEST DAY first, today last.
        const chronologicalByDay = responses.map(r => [...(r.snapshots || [])].reverse());
        const oldestDayFirst = [...chronologicalByDay].reverse();
        const allPoints = oldestDayFirst.flatMap((dayRows, i) => {
          // Label each point with which day it's from, for a clearer
          // x-axis on multi-day ranges (today's rows just use "Time").
          const isToday = i === oldestDayFirst.length - 1;
          return dayRows.map(row => ({
            label: isToday ? row.Time : `${row.Time}`,
            value: row.Spot,
          }));
        });

        if (!cancelled) setPoints(downsample(allPoints));
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [indexName, range]);

  const WIDTH = 700, HEIGHT = 220;
  const chart = points ? buildChartPath(points.map(p => p.value), WIDTH, HEIGHT) : null;
  const latestValue = points && points.length > 0 ? points[points.length - 1].value : null;
  const firstValue = points && points.length > 0 ? points[0].value : null;
  const changeInRange = latestValue != null && firstValue != null ? latestValue - firstValue : null;
  const changePct = changeInRange != null && firstValue ? (changeInRange / firstValue) * 100 : null;
  const isPos = (changeInRange ?? 0) >= 0;

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-bold text-white">{DISPLAY_NAME[indexName] || indexName}</h3>
          {latestValue != null && (
            <div className="flex items-baseline gap-2 mt-0.5">
              <span className="text-xl font-bold text-white tabular-nums">{latestValue.toLocaleString('en-IN')}</span>
              {changePct != null && (
                <span className={`text-xs font-medium ${isPos ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {isPos ? '+' : ''}{changeInRange.toFixed(2)} ({isPos ? '+' : ''}{changePct.toFixed(2)}%)
                </span>
              )}
              {marketStatus && (
                <span className={`text-[9px] font-semibold uppercase tracking-wider ${marketStatus.isOpen ? 'text-emerald-500' : 'text-slate-500'}`}>
                  {marketStatus.isOpen ? 'LIVE' : 'CLOSED · LAST'}
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex gap-1 bg-slate-900/50 p-0.5 rounded-lg">
          {RANGES.map(r => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`text-[11px] font-medium px-2.5 py-1 rounded-md transition-colors ${
                range === r ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="h-[220px] rounded-lg bg-slate-900/30 animate-pulse" />
      ) : error ? (
        <div className="h-[220px] flex items-center justify-center text-sm text-rose-400">⚠ {error}</div>
      ) : !chart ? (
        <div className="h-[220px] flex items-center justify-center text-sm text-slate-500">Not enough data yet for this range.</div>
      ) : (
        <div>
          <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full h-auto" style={{ maxHeight: HEIGHT }}>
            <path d={chart.path} fill="none" stroke={isPos ? '#34d399' : '#fb7185'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div className="flex items-center justify-between text-[10px] text-slate-500 mt-1">
            <span>{points[0]?.label}</span>
            <span>Low {chart.min.toLocaleString('en-IN')} · High {chart.max.toLocaleString('en-IN')}</span>
            <span>{points[points.length - 1]?.label}</span>
          </div>
        </div>
      )}
    </div>
  );
}
