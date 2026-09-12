import { useEffect, useState } from 'react';

// Relative on purpose -- see the same note in SignalList.jsx. Routes
// through Vite's dev-server proxy so this works from any host the page
// was loaded from (localhost, home wifi, Tailscale) with no changes.
const API_BASE = import.meta.env.VITE_API_URL || '';

// Aug 29 2026: Market Status logic -- copied verbatim from
// MarketSummary.jsx (11 status-logic tests + 3 timezone tests already
// passed there), not re-derived. Same honest limitation carried over:
// weekday + time-of-day only, no NSE holiday calendar wired in
// anywhere in this project.
//
// Sep 12 2026 (dashboard redesign): the big clock/status DISPLAY
// (badge + date + time + "Opens 9:15 AM...") moved out of this
// component's card row and into the top header -- see
// MarketStatusHeader.jsx, a new small component with its own copy of
// this same logic. This computation STAYS here, though: NIFTY/
// BANKNIFTY/SENSEX cards below still need isMarketOpen to decide
// PRICE vs INDICATIVE, same as before -- only the big visual clock
// block was moved, not the underlying "is NSE open right now" check.
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

// Sep 12 2026: CRUDEOIL/GOLD/SILVER trade on MCX hours (~9:00 AM -
// 11:30 PM), genuinely different from NSE's 9:15 AM-3:30 PM above --
// reusing marketStatus for these three would mislabel PRICE as
// INDICATIVE (or vice versa) any time the two markets' hours diverge,
// which is most of the day. Copied verbatim from CrudeOilTracker.jsx's
// own computeMcxStatus (tested there in test_mcx_status.js, 9 cases
// including the near-midnight close NSE's hours never had to handle)
// rather than re-derived.
const MCX_OPEN_MIN = 9 * 60;        // 9:00 AM
const MCX_CLOSE_MIN = 23 * 60 + 30; // 11:30 PM

function computeMcxStatus(day, totalMinutes) {
  const isWeekday = day >= 1 && day <= 5;
  const isWithinHours = totalMinutes >= MCX_OPEN_MIN && totalMinutes < MCX_CLOSE_MIN;
  const isOpen = isWeekday && isWithinHours;

  if (isOpen) {
    return { isOpen: true, label: 'Market Open', nextEvent: 'Closes at 11:30 PM' };
  }

  let daysUntilNextOpen = 0;
  let candidateDay = day;

  if (isWeekday && totalMinutes < MCX_OPEN_MIN) {
    daysUntilNextOpen = 0;
  } else {
    do {
      candidateDay = (candidateDay + 1) % 7;
      daysUntilNextOpen++;
    } while (candidateDay === 0 || candidateDay === 6);
  }

  const dayLabel = daysUntilNextOpen === 0 ? 'today' : (daysUntilNextOpen === 1 ? 'tomorrow' : `on ${DAY_NAMES[candidateDay]}`);
  return { isOpen: false, label: 'Market Closed', nextEvent: `Opens 9:00 AM ${dayLabel}` };
}

// Aug 28 2026: pure SVG sparkline -- same coordinate-transform pattern
// already tested for DailyBacktestTab.jsx's EquityCurveChart (verified
// there against flat/single-point/rising/falling edge cases before
// ever being wired in), reused here rather than re-deriving the math.
// REAL historical data only, no fake/interpolated points. Renders
// nothing (not a flat fake line) if there aren't at least 2 real
// points yet -- e.g. right after market open, or before today's first
// snapshot has logged.
//
// Sep 12 2026: shrunk from 64x24 to 44x18 as part of the dashboard
// redesign's "keep sparklines subtle and compact" request -- purely a
// size change, same math, same real-data-only behavior.
function Sparkline({ values, width = 44, height = 18 }) {
  const clean = (values || []).filter(v => v != null && !isNaN(v));
  if (clean.length < 2) return null;

  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const range = max - min || 1;
  const stepX = width / (clean.length - 1);
  const coords = clean.map((v, i) => {
    const x = i * stepX;
    const y = height - ((v - min) / range) * height;
    return [x, y];
  });
  const path = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  const isUp = clean[clean.length - 1] >= clean[0];
  const color = isUp ? '#34d399' : '#fb7185'; // emerald-400 / rose-400 -- same palette as EquityCurveChart

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="overflow-visible shrink-0">
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function MarketBanner() {
  const [data, setData] = useState(null);
  const [marketStatus, setMarketStatus] = useState(null);
  const [mcxStatus, setMcxStatus] = useState(null);

  useEffect(() => {
    const update = () => {
      const { day, totalMinutes } = getIstDayAndMinutes(new Date());
      setMarketStatus(computeMarketStatus(day, totalMinutes));
      setMcxStatus(computeMcxStatus(day, totalMinutes));
    };
    update();
    const interval = setInterval(update, 30000);
    return () => clearInterval(interval);
  }, []);

  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(null);
  // Separate, independent fetch from the Index Tracker endpoint that's
  // already confirmed working -- NOT wired into /api/market-summary/
  // (that endpoint's cache is populated by the NSE-hours-gated worker
  // only, so it has no crude oil data at all). Deliberately doesn't
  // gate the whole banner's loading state -- if this one's slow or
  // fails, NIFTY/BANKNIFTY still render normally.
  const [crudeRow, setCrudeRow] = useState(null);
  const [niftyHistory, setNiftyHistory] = useState([]);
  const [bankHistory, setBankHistory] = useState([]);
  const [crudeHistory, setCrudeHistory] = useState([]);
  const [sensexHistory, setSensexHistory] = useState([]);
  // Sep 12 2026: real per-instrument expiry ("is today THIS
  // instrument's own real contract expiry"), sourced from
  // IndexTrackerView's expiry_date/is_expiry_today fields -- same
  // fetches already below, no new requests. Six flags, not one shared
  // boolean: each instrument's real expiry is independent, never one
  // hardcoded weekday applied to all.
  const [niftyExpiryToday, setNiftyExpiryToday] = useState(false);
  const [bankExpiryToday, setBankExpiryToday] = useState(false);
  const [sensexExpiryToday, setSensexExpiryToday] = useState(false);
  const [crudeExpiryToday, setCrudeExpiryToday] = useState(false);
  const [goldExpiryToday, setGoldExpiryToday] = useState(false);
  const [silverExpiryToday, setSilverExpiryToday] = useState(false);
  // Sep 12 2026: GOLD/SILVER banner cards -- same exact pattern
  // crudeRow/crudeHistory already use (their own dedicated Index
  // Tracker fetch below), not the market-summary cache (which has no
  // commodity data at all).
  const [goldRow, setGoldRow] = useState(null);
  const [goldHistory, setGoldHistory] = useState([]);
  const [silverRow, setSilverRow] = useState(null);
  const [silverHistory, setSilverHistory] = useState([]);

  useEffect(() => {
    let mounted = true;
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/market-summary/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (mounted) { setData(json); setFetchError(null); }
      } catch (err) {
        console.error('Market fetch error:', err);
        if (mounted) setFetchError(err.message || 'Fetch failed');
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  useEffect(() => {
    let mounted = true;
    const fetchCrude = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/index-tracker/CRUDEOIL/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        const snapshots = json.snapshots || [];
        if (mounted) {
          setCrudeRow(snapshots[0] || null);
          setCrudeHistory([...snapshots].reverse().map(s => s.Fut));
          setCrudeExpiryToday(!!json.is_expiry_today);
        }
      } catch (err) {
        console.error('Crude oil fetch error:', err);
      }
    };
    fetchCrude();
    const interval = setInterval(fetchCrude, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  // Sep 12 2026: GOLD/SILVER banner cards -- exact same fetch shape as
  // CRUDEOIL above, against the same already-existing, already-running
  // Index Tracker endpoint (GOLD/SILVER's own snapshot cycle already
  // populates this regardless of whether anything reads it here -- no
  // new Fyers call, no new backend polling, just a new frontend reader
  // of data that's already flowing).
  useEffect(() => {
    let mounted = true;
    const fetchGold = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/index-tracker/GOLD/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        const snapshots = json.snapshots || [];
        if (mounted) {
          setGoldRow(snapshots[0] || null);
          setGoldHistory([...snapshots].reverse().map(s => s.Fut));
          setGoldExpiryToday(!!json.is_expiry_today);
        }
      } catch (err) {
        console.error('Gold fetch error:', err);
      }
    };
    fetchGold();
    const interval = setInterval(fetchGold, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  useEffect(() => {
    let mounted = true;
    const fetchSilver = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/index-tracker/SILVER/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        const snapshots = json.snapshots || [];
        if (mounted) {
          setSilverRow(snapshots[0] || null);
          setSilverHistory([...snapshots].reverse().map(s => s.Fut));
          setSilverExpiryToday(!!json.is_expiry_today);
        }
      } catch (err) {
        console.error('Silver fetch error:', err);
      }
    };
    fetchSilver();
    const interval = setInterval(fetchSilver, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  // Aug 28 2026: real intraday history for the NIFTY/BANKNIFTY
  // sparklines -- reuses the SAME Index Tracker endpoint the Index
  // Tracker tab itself already reads, no new backend endpoint needed.
  useEffect(() => {
    let mounted = true;
    const fetchHistories = async () => {
      try {
        const [niftyRes, bankRes, sensexRes] = await Promise.all([
          fetch(`${API_BASE}/api/index-tracker/NIFTY/`),
          fetch(`${API_BASE}/api/index-tracker/BANKNIFTY/`),
          fetch(`${API_BASE}/api/index-tracker/SENSEX/`),
        ]);
        const niftyJson = niftyRes.ok ? await niftyRes.json() : { snapshots: [] };
        const bankJson = bankRes.ok ? await bankRes.json() : { snapshots: [] };
        const sensexJson = sensexRes.ok ? await sensexRes.json() : { snapshots: [] };
        const niftySnaps = [...(niftyJson.snapshots || [])].reverse();
        const bankSnaps = [...(bankJson.snapshots || [])].reverse();
        const sensexSnaps = [...(sensexJson.snapshots || [])].reverse();
        if (mounted) {
          setNiftyHistory(niftySnaps.map(s => s.Spot));
          setBankHistory(bankSnaps.map(s => s.Spot));
          setSensexHistory(sensexSnaps.map(s => s.Spot));
          setNiftyExpiryToday(!!niftyJson.is_expiry_today);
          setBankExpiryToday(!!bankJson.is_expiry_today);
          setSensexExpiryToday(!!sensexJson.is_expiry_today);
        }
      } catch (err) {
        console.error('Index history fetch error:', err);
      }
    };
    fetchHistories();
    const interval = setInterval(fetchHistories, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  // Aug 27 2026: the ACTUAL live-resolved Fyers symbol for crude oil's
  // rolling front-month contract (e.g. MCX:CRUDEOIL26AUGFUT) -- powers
  // the chart link below. Fetched ONCE on mount, not on the 30s
  // interval the price/crudeRow fetches use.
  const [crudeSymbol, setCrudeSymbol] = useState(null);
  useEffect(() => {
    let mounted = true;
    fetch(`${API_BASE}/api/commodity-symbol/CRUDEOIL/`)
      .then(res => res.ok ? res.json() : { symbol: null })
      .then(json => { if (mounted) setCrudeSymbol(json.symbol || null); })
      .catch(() => { if (mounted) setCrudeSymbol(null); });
    return () => { mounted = false; };
  }, []);

  // Aug 29 2026: per the PDF's own data-state table -- a null/missing
  // price is NOT the same as a genuine 0.00, and showing them
  // identically is exactly the "ambiguous zero" problem it flagged.
  // Returns null (not the string '0.00') so the CALLER decides how to
  // display "no data" -- tested in test_data_state.js.
  const fmt = (n) => {
    if (n === null || n === undefined || isNaN(n)) return null;
    return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  // Tested in test_data_state.js (6 cases, including the important
  // "a genuine 0 price must still show as live, not be confused with
  // missing data" case -- uses == null, not a falsy check).
  const determineDataState = (price, isMarketOpen, err) => {
    if (err) return 'error';
    if (price == null) return 'no_data';
    return isMarketOpen ? 'live' : 'closed';
  };

  // Aug 27 2026: fixed path -- was '/popout_chart/index.html', which
  // isn't a real Fyers route (confirmed against Fyers' own community
  // forum: the correct, working popout path is '/popout/index.html').
  const fyersChartUrl = (symbol) =>
    `https://trade.fyers.in/popout/index.html?symbol=${encodeURIComponent(symbol)}&resolution=5&theme=light`;

  // Sep 12 2026: dashboard redesign -- compact layout per explicit
  // reference: name+status on one row, big price + sparkline on the
  // next, change/% below that, then the two conditional lines
  // (Indicative, Expiry Today). showPriceLabel is gone -- every card
  // using this component is now in the six-instrument scope, so the
  // Indicative logic applies uniformly rather than needing an opt-in
  // flag.
  //
  // "Indicative" is the SAME real price this card already has, shown
  // as a small secondary caption -- never a second, separately-sourced
  // number (no such field exists anywhere in this app's real data, and
  // inventing one would violate this whole project's no-fabrication
  // rule). Main price never gets replaced by it -- the big number is
  // always the real last-known price, live or not; Indicative only
  // adds a small clarifying line underneath when the state genuinely
  // isn't live.
  const Card = ({ label, price, change, changePercent, fyersSymbol, sparklineData, isMarketOpen, err, isExpiryToday = false }) => {
    const state = determineDataState(price, isMarketOpen, err);
    // Sep 12 2026: falls back to changePercent's own sign when no
    // absolute change is available (CRUDEOIL/GOLD/SILVER's Index
    // Tracker row has no raw "Change" field, only "Change %" -- see
    // the render calls below). Without this fallback, `change`
    // being undefined would make isPos default to true regardless of
    // real direction.
    const isPos = change != null ? change >= 0 : (changePercent || 0) >= 0;
    const arrow = isPos ? '↗' : '↘';

    const priceStr = fmt(price);
    const changeStr = fmt(change);
    const changePctStr = fmt(changePercent);

    const dotClass = state === 'live'
      ? `${isPos ? 'bg-emerald-500' : 'bg-rose-500'} animate-pulse`
      : state === 'error' ? 'bg-amber-500'
      : 'bg-slate-500';

    const statusText = state === 'live' ? 'LIVE' : state === 'closed' ? 'CLOSED' : state === 'error' ? 'ERROR' : 'N/A';
    const statusColor = state === 'live' ? 'text-emerald-500' : state === 'error' ? 'text-amber-500' : 'text-slate-500';

    const showIndicative = state !== 'live' && priceStr != null;

    const inner = (
      <div className={`flex flex-col gap-0.5 px-3 py-2.5 rounded-xl bg-slate-800/60 border border-slate-700/50 h-full md:min-w-[150px] md:flex-1 ${fyersSymbol ? 'hover:border-blue-500/50 hover:bg-slate-800/90 transition-colors cursor-pointer group' : ''}`}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider truncate flex items-center gap-1">
            {label}
            {fyersSymbol && <span className="opacity-0 group-hover:opacity-100 transition-opacity text-blue-400 shrink-0 normal-case">↗</span>}
          </span>
          <span className="flex items-center gap-1 shrink-0">
            <span className={`w-1.5 h-1.5 rounded-full ${dotClass}`} />
            <span className={`text-[9px] font-semibold uppercase tracking-wider ${statusColor}`}>{statusText}</span>
          </span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <p className="text-xl font-bold text-white tabular-nums tier-critical leading-tight">{priceStr ?? 'N/A'}</p>
          <Sparkline values={sparklineData} />
        </div>
        <p className={`text-[11px] font-medium leading-tight ${state === 'live' ? (isPos ? 'text-emerald-400' : 'text-rose-400') : 'text-slate-500'}`}>
          {priceStr != null ? `${arrow} ${isPos ? '+' : ''}${changeStr ?? '—'} (${isPos ? '+' : ''}${changePctStr ?? '—'}%)` : '—'}
        </p>
        {showIndicative && (
          <p className="text-[10px] text-slate-500 leading-tight">Indicative: {priceStr}</p>
        )}
        {isExpiryToday && (
          <span className="inline-block w-fit text-[8px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/30 mt-0.5">
            Expiry Today
          </span>
        )}
      </div>
    );

    if (!fyersSymbol) return inner;
    return (
      <a href={fyersChartUrl(fyersSymbol)} target="_blank" rel="noopener noreferrer" title={`Open ${label} chart on Fyers`} className="block h-full md:min-w-[150px] md:flex-1">
        {inner}
      </a>
    );
  };

  if (loading || !data) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mb-4">
        {[1,2,3,4,5,6].map(i => (
          <div key={i} className="h-[92px] rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />
        ))}
      </div>
    );
  }

  const nifty = data.nifty50 || {};
  const bank = data.banknifty || {};
  const sensex = data.sensex || {};
  const crudePrice = crudeRow?.Fut;
  const crudeChangePct = crudeRow?.['Change %'];
  const goldPrice = goldRow?.Fut;
  const goldChangePct = goldRow?.['Change %'];
  const silverPrice = silverRow?.Fut;
  const silverChangePct = silverRow?.['Change %'];

  return (
    <div className="grid grid-cols-2 gap-3 mb-4 md:flex md:overflow-x-auto md:pb-1 md:items-stretch">
      <Card label="NIFTY" price={nifty.price} change={nifty.change} changePercent={nifty.change_percent} fyersSymbol="NSE:NIFTY50-INDEX" sparklineData={niftyHistory} isMarketOpen={marketStatus?.isOpen} err={fetchError} isExpiryToday={niftyExpiryToday} />
      <Card label="BANKNIFTY" price={bank.price} change={bank.change} changePercent={bank.change_percent} fyersSymbol="NSE:NIFTYBANK-INDEX" sparklineData={bankHistory} isMarketOpen={marketStatus?.isOpen} err={fetchError} isExpiryToday={bankExpiryToday} />
      <Card label="SENSEX" price={sensex.price} change={sensex.change} changePercent={sensex.change_percent} fyersSymbol="BSE:SENSEX-INDEX" sparklineData={sensexHistory} isMarketOpen={marketStatus?.isOpen} err={fetchError} isExpiryToday={sensexExpiryToday} />
      {/* CRUDEOIL/GOLD/SILVER: no absolute "Change" field exists on
          the Index Tracker row (COLUMNS only has "Change %"), so
          `change` is deliberately left unpassed rather than guessing
          one -- Card's changeStr shows '—' for it, same "never
          fabricate" rule as everywhere else in this project. */}
      <Card label="CRUDE OIL" price={crudePrice} changePercent={crudeChangePct} fyersSymbol={crudeSymbol || undefined} sparklineData={crudeHistory} isMarketOpen={mcxStatus?.isOpen} err={null} isExpiryToday={crudeExpiryToday} />
      <Card label="GOLD" price={goldPrice} changePercent={goldChangePct} sparklineData={goldHistory} isMarketOpen={mcxStatus?.isOpen} err={null} isExpiryToday={goldExpiryToday} />
      <Card label="SILVER" price={silverPrice} changePercent={silverChangePct} sparklineData={silverHistory} isMarketOpen={mcxStatus?.isOpen} err={null} isExpiryToday={silverExpiryToday} />
    </div>
  );
}
