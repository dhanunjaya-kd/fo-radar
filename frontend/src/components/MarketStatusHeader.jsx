import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Sep 12 2026: extracted from MarketBanner.jsx's card row into the top
// header, per explicit request -- freeing the full banner row width
// for the six instrument cards. Same tested status logic (11 status-
// logic tests + 3 timezone tests, per MarketBanner.jsx's own original
// comment) copied verbatim rather than re-derived; MarketBanner.jsx
// keeps its OWN separate copy of this computation too (still needed
// there for the cards' PRICE vs INDICATIVE decision) -- this component
// only owns the VISUAL clock/status display now, not the underlying
// "is NSE open" check other things still depend on.
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

// Sep 12 2026: this naive weekday-only computation is now ONLY a
// fallback, used when the new holiday-aware backend endpoint
// (/api/next-trading-session/NSE/) can't be reached -- "fail
// conservatively" per the explicit requirement, meaning fall back to
// the pre-existing, already-accepted behavior rather than hide the
// message or invent something new. isOpen itself is still fully
// real-time-computed here (that part never needed a calendar), only
// the "next open" WORDING falls back to plain-weekday when the
// holiday-aware fetch hasn't landed yet.
function computeMarketStatus(day, totalMinutes) {
  const isWeekday = day >= 1 && day <= 5;
  const isWithinHours = totalMinutes >= MARKET_OPEN_MIN && totalMinutes < MARKET_CLOSE_MIN;
  const isOpen = isWeekday && isWithinHours;

  if (isOpen) {
    return { isOpen: true, label: 'Market Open', nextSessionText: null };
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

  const dayLabel = daysUntilNextOpen === 0 ? 'Today' : (daysUntilNextOpen === 1 ? 'Tomorrow' : DAY_NAMES[candidateDay]);
  return { isOpen: false, label: 'Market Closed', nextSessionText: `${dayLabel} · 9:15 AM` };
}

export default function MarketStatusHeader() {
  const [now, setNow] = useState(new Date());
  const [marketStatus, setMarketStatus] = useState(null);
  // Sep 12 2026: real, holiday-aware next session from the backend
  // (see market_hours.get_next_trading_session()) -- null until it
  // resolves or if the fetch fails, in which case the render below
  // falls back to marketStatus.nextSessionText's plain-weekday guess
  // rather than showing nothing.
  const [holidayAwareSession, setHolidayAwareSession] = useState(null);

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

  // Sep 12 2026: separate, much slower interval -- a holiday-aware
  // next session doesn't change within a day, no reason to hit this
  // every second like the clock above. NSE specifically: this header's
  // single Market Status badge has always reflected NSE hours (see
  // marketStatus above), so its "next session" should stay consistent
  // with that, not introduce a second, different market's calendar
  // into the same badge.
  useEffect(() => {
    let mounted = true;
    const fetchSession = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/next-trading-session/NSE/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (mounted) setHolidayAwareSession(json.next_session || null);
      } catch (err) {
        console.error('Next trading session fetch error (falling back to plain-weekday):', err);
        if (mounted) setHolidayAwareSession(null);
      }
    };
    fetchSession();
    const interval = setInterval(fetchSession, 300000); // 5 min -- this genuinely never changes faster than once a day
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (!marketStatus) return null;

  const timeStr = new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(now);
  const dateStr = new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata', weekday: 'short', day: '2-digit', month: 'short', year: 'numeric',
  }).format(now);

  // Real, holiday-aware text when the backend resolved one; otherwise
  // the plain-weekday fallback computed locally above. Never shown at
  // all while the market is genuinely open (nothing to announce).
  const nextSessionText = marketStatus.isOpen
    ? null
    : holidayAwareSession
      ? `${new Date(holidayAwareSession.date + 'T00:00:00').toLocaleDateString('en-IN', { weekday: 'long' })} · 9:15 AM`
      : marketStatus.nextSessionText;

  return (
    <div className="flex flex-col items-end gap-0.5 px-3.5 py-1.5 rounded-xl bg-slate-900/60 border border-slate-700/50 whitespace-nowrap">
      <div className="flex items-center gap-3">
        <span className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${marketStatus.isOpen ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'}`} />
          <span className={`text-sm font-semibold ${marketStatus.isOpen ? 'text-emerald-400' : 'text-rose-400'}`}>{marketStatus.label}</span>
        </span>
        <span className="text-slate-600">|</span>
        <span className="text-sm text-slate-300">{dateStr}</span>
        <span className="text-sm font-bold text-white tabular-nums">{timeStr}</span>
      </div>
      {nextSessionText && (
        <div className="text-[11px] text-slate-500">
          <span className="text-slate-600">Next Trading Session:</span> {nextSessionText}
        </div>
      )}
    </div>
  );
}
