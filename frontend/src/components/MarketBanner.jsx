import { useEffect, useState } from 'react';

// Relative on purpose -- see the same note in SignalList.jsx. Routes
// through Vite's dev-server proxy so this works from any host the page
// was loaded from (localhost, home wifi, Tailscale) with no changes.
const API_BASE = import.meta.env.VITE_API_URL || '';

// Aug 29 2026: Market Status, moved here from its own standalone card
// in Market View -- now shown globally next to the time/date, since
// whether the market's open matters on every tab, not just Market
// View. Logic copied verbatim from MarketSummary.jsx (11 status-logic
// tests + 3 timezone tests already passed there), not re-derived.
// Same honest limitation carried over: weekday + time-of-day only, no
// NSE holiday calendar wired in anywhere in this project.
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

// Aug 28 2026: pure SVG sparkline -- same coordinate-transform pattern
// already tested for DailyBacktestTab.jsx's EquityCurveChart (verified
// there against flat/single-point/rising/falling edge cases before
// ever being wired in), reused here rather than re-deriving the math.
// REAL historical data only, no fake/interpolated points: NIFTY/
// BANKNIFTY/VIX come from Index Tracker's own logged Spot/VIX history
// (already real, already written every ~60s cycle); Crude reuses the
// same snapshot fetch this component already makes for its current
// price, just keeping the full series instead of only the latest row.
// Renders nothing (not a flat fake line) if there aren't at least 2
// real points yet -- e.g. right after market open, or before today's
// first snapshot has logged.
function Sparkline({ values, width = 64, height = 24 }) {
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

  // Own independent clock, same as MarketSummary.jsx used -- reflects
  // right now, not whenever the backend's data.timestamp last updated
  // (which could be stale if the last fetch failed or is slow).
  useEffect(() => {
    const update = () => {
      const { day, totalMinutes } = getIstDayAndMinutes(new Date());
      setMarketStatus(computeMarketStatus(day, totalMinutes));
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
  // fails, NIFTY/BANKNIFTY/VIX/PCR still render normally.
  const [crudeRow, setCrudeRow] = useState(null);
  // Aug 28 2026: sparkline series for all 4 cards. NIFTY/BANKNIFTY/VIX
  // fetched fresh below; Crude's is derived from the SAME snapshot
  // fetch crudeRow already uses (no extra request).
  const [niftyHistory, setNiftyHistory] = useState([]);
  const [bankHistory, setBankHistory] = useState([]);
  const [vixHistory, setVixHistory] = useState([]);
  const [crudeHistory, setCrudeHistory] = useState([]);

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
          // get_today_snapshots() already returns most-recent-first, so [0]
          // is the latest row -- null if nothing logged yet today.
          setCrudeRow(snapshots[0] || null);
          // Sparkline wants chronological (oldest-first) order --
          // reversed here, same convention as the NIFTY/BANKNIFTY/VIX
          // fetch below and DailyBacktestTab's equity curve.
          setCrudeHistory([...snapshots].reverse().map(s => s.Fut));
        }
      } catch (err) {
        console.error('Crude oil fetch error:', err);
      }
    };
    fetchCrude();
    const interval = setInterval(fetchCrude, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  // Aug 28 2026: real intraday history for the NIFTY/BANKNIFTY/VIX
  // sparklines -- reuses the SAME Index Tracker endpoint the Index
  // Tracker tab itself already reads, no new backend endpoint needed.
  // VIX is logged as its own column on every NIFTY snapshot row (the
  // same real VIX value either way -- see index_tracker.py's
  // snapshot_index(), vix is passed in once per cycle and logged on
  // both indices' rows), so NIFTY's history is reused as VIX's source
  // rather than fetching BANKNIFTY a third time for the same number.
  useEffect(() => {
    let mounted = true;
    const fetchHistories = async () => {
      try {
        const [niftyRes, bankRes] = await Promise.all([
          fetch(`${API_BASE}/api/index-tracker/NIFTY/`),
          fetch(`${API_BASE}/api/index-tracker/BANKNIFTY/`),
        ]);
        const niftyJson = niftyRes.ok ? await niftyRes.json() : { snapshots: [] };
        const bankJson = bankRes.ok ? await bankRes.json() : { snapshots: [] };
        const niftySnaps = [...(niftyJson.snapshots || [])].reverse();
        const bankSnaps = [...(bankJson.snapshots || [])].reverse();
        if (mounted) {
          setNiftyHistory(niftySnaps.map(s => s.Spot));
          setBankHistory(bankSnaps.map(s => s.Spot));
          setVixHistory(niftySnaps.map(s => s.VIX));
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
  // interval the price/crudeRow fetches use: the resolved contract only
  // changes at most once a month (see index_tracker.py's rollover
  // rules), so there's no need to re-ask this often.
  const [crudeSymbol, setCrudeSymbol] = useState(null);
  useEffect(() => {
    let mounted = true;
    fetch(`${API_BASE}/api/commodity-symbol/CRUDEOIL/`)
      .then(res => res.ok ? res.json() : { symbol: null })
      .then(json => { if (mounted) setCrudeSymbol(json.symbol || null); })
      .catch(() => { if (mounted) setCrudeSymbol(null); }); // card just won't be clickable -- not worth surfacing an error for
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
  // forum: the correct, working popout path is '/popout/index.html',
  // e.g. https://trade.fyers.in/popout/index.html?symbol=NSE:ACC-EQ&
  // resolution=1&theme=light). The extra "_chart" meant every click
  // hit a dead path regardless of which symbol/card was clicked --
  // matches exactly what was reported (nothing opens for any of them).
  // Resolution left at 5 (unchanged) -- that param isn't the bug, only
  // the path segment was wrong.
  const fyersChartUrl = (symbol) =>
    `https://trade.fyers.in/popout/index.html?symbol=${encodeURIComponent(symbol)}&resolution=5&theme=light`;

  // Aug 29 2026: rebuilt for real LIVE / CLOSED / NO DATA / ERROR
  // states, replacing the old always-pulsing-dot-plus-fake-0.00
  // display. isMarketOpen comes from this component's own tested
  // marketStatus (added earlier), not re-derived here.
  const Card = ({ label, price, change, changePercent, fyersSymbol, sparklineData, isMarketOpen, err }) => {
    const state = determineDataState(price, isMarketOpen, err);
    const isPos = (change || 0) >= 0;
    const arrow = isPos ? '↗' : '↘';

    const priceStr = fmt(price);
    const changeStr = fmt(change);
    const changePctStr = fmt(changePercent);

    const dotClass = state === 'live'
      ? `${isPos ? 'bg-emerald-500' : 'bg-rose-500'} animate-pulse`
      : state === 'error' ? 'bg-amber-500'
      : 'bg-slate-600'; // closed or no_data -- static, muted, deliberately NOT pulsing like live data

    const statusLabel = state === 'live' ? 'LIVE'
      : state === 'closed' ? 'CLOSED · LAST'
      : state === 'error' ? 'DATA ERROR'
      : 'DATA UNAVAILABLE';
    const statusColor = state === 'live' ? 'text-emerald-500'
      : state === 'error' ? 'text-amber-500'
      : 'text-slate-500';

    const inner = (
      <div className={`flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-800/60 border border-slate-700/50 ${fyersSymbol ? 'hover:border-blue-500/50 hover:bg-slate-800/90 transition-colors cursor-pointer group' : ''}`}>
        <div className={`w-2 h-2 rounded-full ${dotClass}`} />
        <div className="flex-1">
          <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider flex items-center gap-1">
            {label}
            {fyersSymbol && <span className="opacity-0 group-hover:opacity-100 transition-opacity text-blue-400">↗ chart</span>}
          </p>
          {priceStr != null ? (
            <>
              <p className="text-lg font-bold text-white tabular-nums tier-critical">{priceStr}</p>
              <p className={`text-xs font-medium ${state === 'live' ? (isPos ? 'text-emerald-400' : 'text-rose-400') : 'text-slate-500'}`}>
                {arrow} {isPos ? '+' : ''}{changeStr ?? '—'} ({isPos ? '+' : ''}{changePctStr ?? '—'}%)
              </p>
            </>
          ) : (
            <p className="text-lg font-bold text-slate-600 tabular-nums">—</p>
          )}
          <p className={`text-[9px] font-semibold uppercase tracking-wider mt-0.5 ${statusColor}`}>{statusLabel}</p>
        </div>
        <Sparkline values={sparklineData} />
      </div>
    );

    if (!fyersSymbol) return inner;
    return (
      <a href={fyersChartUrl(fyersSymbol)} target="_blank" rel="noopener noreferrer" title={`Open ${label} chart on Fyers`}>
        {inner}
      </a>
    );
  };

  if (loading || !data) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        {[1,2,3,4].map(i => (
          <div key={i} className="h-20 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />
        ))}
      </div>
    );
  }

  const nifty = data.nifty50 || {};
  const bank = data.banknifty || {};
  const vix = data.india_vix || {};
  const pcr = data.pcr || {};
  const crudePrice = crudeRow?.Fut;
  const crudeChangePct = crudeRow?.['Change %'];
  const crudeIsPos = (crudeChangePct || 0) >= 0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mb-4">
      <Card label="NIFTY 50" price={nifty.price} change={nifty.change} changePercent={nifty.change_percent} fyersSymbol="NSE:NIFTY50-INDEX" sparklineData={niftyHistory} isMarketOpen={marketStatus?.isOpen} err={fetchError} />
      <Card label="BANKNIFTY" price={bank.price} change={bank.change} changePercent={bank.change_percent} fyersSymbol="NSE:NIFTYBANK-INDEX" sparklineData={bankHistory} isMarketOpen={marketStatus?.isOpen} err={fetchError} />
      <Card label="INDIA VIX" price={vix.price ?? vix.value} change={vix.change} changePercent={vix.change_percent} fyersSymbol="NSE:INDIAVIX-INDEX" sparklineData={vixHistory} isMarketOpen={marketStatus?.isOpen} err={fetchError} />

      {/* PCR -- kept in its own distinct shape (sentiment label
          instead of change%, no sparkline), but now uses the same
          LIVE/CLOSED/DATA UNAVAILABLE status labeling as every other
          card, instead of its own separate "N/A" convention. */}
      <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-800/60 border border-slate-700/50">
        <div className={`w-2 h-2 rounded-full ${pcr.value != null && marketStatus?.isOpen ? 'bg-purple-500 animate-pulse' : 'bg-slate-600'}`} />
        <div>
          <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">PCR</p>
          <p className="text-lg font-bold text-white tabular-nums tier-important">{pcr.value != null ? pcr.value.toFixed(2) : '—'}</p>
          <p className={`text-xs font-medium ${pcr.value != null ? 'text-purple-400' : 'text-slate-500'}`}>{pcr.value != null ? (pcr.sentiment || 'N/A') : 'Data unavailable'}</p>
          <p className={`text-[9px] font-semibold uppercase tracking-wider mt-0.5 ${
            fetchError ? 'text-amber-500' : pcr.value == null ? 'text-slate-500' : marketStatus?.isOpen ? 'text-emerald-500' : 'text-slate-500'
          }`}>
            {fetchError ? 'DATA ERROR' : pcr.value == null ? 'DATA UNAVAILABLE' : marketStatus?.isOpen ? 'LIVE' : 'CLOSED · LAST'}
          </p>
        </div>
      </div>

      {/* Crude Oil -- separate source (Index Tracker's endpoint, not
          market-summary). Chart link now wired up (Aug 27 2026) via
          crudeSymbol, the live-resolved rolling contract fetched above
          -- previously omitted because nothing exposed that resolved
          string to this component and hardcoding it would go stale
          within weeks. Falls back to a plain (non-clickable) card if
          the resolve hasn't landed yet or came back None, same as
          every other "don't guess" fallback in this project. */}
      {crudeSymbol ? (
        <a href={fyersChartUrl(crudeSymbol)} target="_blank" rel="noopener noreferrer" title="Open CRUDE OIL chart on Fyers"
          className="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-800/60 border border-slate-700/50 hover:border-blue-500/50 hover:bg-slate-800/90 transition-colors cursor-pointer group">
          <div className={`w-2 h-2 rounded-full ${crudeIsPos ? 'bg-emerald-500' : 'bg-rose-500'} animate-pulse`} />
          <div className="flex-1">
            <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider flex items-center gap-1">
              CRUDE OIL
              <span className="opacity-0 group-hover:opacity-100 transition-opacity text-blue-400">↗ chart</span>
            </p>
            <p className="text-lg font-bold text-white tabular-nums tier-critical">{fmt(crudePrice) ?? '—'}</p>
            <p className={`text-xs font-medium ${crudeIsPos ? 'text-emerald-400' : 'text-rose-400'}`}>
              {crudeChangePct != null ? `${crudeIsPos ? '↗ +' : '↘ '}${crudeChangePct.toFixed(2)}%` : '—'}
            </p>
          </div>
          <Sparkline values={crudeHistory} />
        </a>
      ) : (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-800/60 border border-slate-700/50">
          <div className={`w-2 h-2 rounded-full ${crudeIsPos ? 'bg-emerald-500' : 'bg-rose-500'} animate-pulse`} />
          <div className="flex-1">
            <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">CRUDE OIL</p>
            <p className="text-lg font-bold text-white tabular-nums tier-critical">{fmt(crudePrice) ?? '—'}</p>
            <p className={`text-xs font-medium ${crudeIsPos ? 'text-emerald-400' : 'text-rose-400'}`}>
              {crudeChangePct != null ? `${crudeIsPos ? '↗ +' : '↘ '}${crudeChangePct.toFixed(2)}%` : '—'}
            </p>
          </div>
          <Sparkline values={crudeHistory} />
        </div>
      )}

      {/* Time + Market Status -- moved here from its own standalone
          card in Market View, per direct feedback: whether the market
          is open matters globally, not just on one tab. */}
      <div className="hidden md:flex items-center justify-end px-4 py-3">
        <div className="text-right">
          {marketStatus && (
            <div className="flex items-center justify-end gap-1.5 mb-1">
              <span className={`w-1.5 h-1.5 rounded-full ${marketStatus.isOpen ? 'bg-emerald-500 animate-pulse' : 'bg-slate-500'}`} />
              <span className={`text-xs font-semibold ${marketStatus.isOpen ? 'text-emerald-400' : 'text-slate-400'}`}>{marketStatus.label}</span>
            </div>
          )}
          <p className="text-xs text-slate-400 font-mono">
            {new Date(data.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
          </p>
          <p className="text-[10px] text-slate-500 font-mono">
            {new Date(data.timestamp).toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' })}
          </p>
          {marketStatus && <p className="text-[10px] text-slate-600">{marketStatus.nextEvent}</p>}
        </div>
      </div>
    </div>
  );
}
