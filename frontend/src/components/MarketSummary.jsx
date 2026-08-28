import { useEffect, useState } from 'react';

const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MARKET_OPEN_MIN = 9 * 60 + 15;  // 9:15 AM
const MARKET_CLOSE_MIN = 15 * 60 + 30; // 3:30 PM

// Aug 28 2026: this pair of functions is tested exhaustively in
// test_market_status.js (11 cases, including the Friday-close-must-
// skip-to-Monday case) and test_ist_conversion.js (3 cases, including
// the UTC-midnight-rollover edge case) before ever being wired into
// JSX -- copied here unchanged from what was actually tested, not
// re-derived.
//
// HONEST LIMITATION: this is weekday + time-of-day only. It does NOT
// know about NSE trading holidays (Diwali, Republic Day, etc.) -- no
// holiday calendar is wired into this project anywhere. On an actual
// market holiday, this will incorrectly read "Market Open" during
// normal hours. Stated plainly here rather than silently wrong.
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

export default function MarketSummary() {
  const [status, setStatus] = useState(null);
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const update = () => {
      const current = new Date();
      const { day, totalMinutes } = getIstDayAndMinutes(current);
      setStatus(computeMarketStatus(day, totalMinutes));
      setNow(current);
    };
    update();
    const interval = setInterval(update, 30000); // status can only meaningfully change once a minute anyway
    return () => clearInterval(interval);
  }, []);

  if (!status) return null;

  const istTimeStr = now.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: true });

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Market Status</p>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${status.isOpen ? 'bg-emerald-500 animate-pulse' : 'bg-slate-500'}`} />
            <span className={`text-lg font-bold ${status.isOpen ? 'text-emerald-400' : 'text-slate-400'}`}>{status.label}</span>
          </div>
          <p className="text-xs text-slate-500 mt-1">{status.nextEvent}</p>
        </div>
        <div className="text-right">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">IST Time</p>
          <p className="text-lg font-bold text-white tabular-nums">{istTimeStr}</p>
        </div>
      </div>
      {!status.isOpen && (
        <p className="text-[10px] text-slate-600 mt-2">Based on standard NSE hours (9:15 AM–3:30 PM IST, Mon–Fri) — doesn't account for market holidays.</p>
      )}
    </div>
  );
}
