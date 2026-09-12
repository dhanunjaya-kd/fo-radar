import { useEffect, useState } from 'react';

// Sep 12 2026: extracted from MarketBanner.jsx's card row into the top
// header, per explicit request -- freeing the full banner row width
// for the six instrument cards. Same tested status logic (11 status-
// logic tests + 3 timezone tests, per MarketBanner.jsx's own original
// comment) copied verbatim rather than re-derived; MarketBanner.jsx
// keeps its OWN separate copy of this computation too (still needed
// there for the cards' PRICE vs INDICATIVE decision) -- this component
// only owns the VISUAL clock/status display now, not the underlying
// "is NSE open" check other things still depend on.
//
// Uses the browser's own clock (ticked every second) rather than the
// market-summary API's data.timestamp the old inline block used --
// avoids adding a fetch here just to display a clock, and the two are
// close enough for a cosmetic display. Same honest limitation carried
// over: weekday + time-of-day only, no NSE holiday calendar wired in
// anywhere in this project.
const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MARKET_OPEN_MIN = 9 * 60 + 15;  // 9:15 AM
const MARKET_CLOSE_MIN = 15 * 60 + 30; // 3:30 PM

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

export default function MarketStatusHeader() {
  const [now, setNow] = useState(new Date());
  const [marketStatus, setMarketStatus] = useState(null);

  useEffect(() => {
    const update = () => {
      const n = new Date();
      setNow(n);
      const { day, totalMinutes } = getIstDayAndMinutes(n);
      setMarketStatus(computeMarketStatus(day, totalMinutes));
    };
    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, []);

  if (!marketStatus) return null;

  const timeStr = new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(now);
  const dateStr = new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata', weekday: 'short', day: '2-digit', month: 'short', year: 'numeric',
  }).format(now);

  return (
    <div className="flex items-center gap-3 px-3.5 py-1.5 rounded-full bg-slate-900/60 border border-slate-700/50 whitespace-nowrap">
      <span className="flex items-center gap-1.5">
        <span className={`w-2 h-2 rounded-full ${marketStatus.isOpen ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'}`} />
        <span className={`text-sm font-semibold ${marketStatus.isOpen ? 'text-emerald-400' : 'text-rose-400'}`}>{marketStatus.label}</span>
      </span>
      <span className="text-slate-600">|</span>
      <span className="text-sm text-slate-300">{dateStr}</span>
      <span className="text-sm font-bold text-white tabular-nums">{timeStr}</span>
      <span className="hidden lg:inline text-[11px] text-slate-500">{marketStatus.nextEvent}</span>
    </div>
  );
}
