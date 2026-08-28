import { useEffect, useState } from 'react';

// Relative on purpose -- see the same note in SignalList.jsx. Routes
// through Vite's dev-server proxy so this works from any host the page
// was loaded from (localhost, home wifi, Tailscale) with no changes.
const API_BASE = import.meta.env.VITE_API_URL || '';

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
  const [loading, setLoading] = useState(true);
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
        if (mounted) setData(json);
      } catch (err) {
        console.error('Market fetch error:', err);
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

  const fmt = (n) => {
    if (n === null || n === undefined || isNaN(n)) return '0.00';
    return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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

  const Card = ({ label, price, change, changePercent, fyersSymbol, sparklineData }) => {
    const isPos = (change || 0) >= 0;
    const arrow = isPos ? '↗' : '↘';
    const textColor = isPos ? 'text-emerald-400' : 'text-rose-400';
    const bgDot = isPos ? 'bg-emerald-500' : 'bg-rose-500';

    const inner = (
      <div className={`flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-800/60 border border-slate-700/50 ${fyersSymbol ? 'hover:border-blue-500/50 hover:bg-slate-800/90 transition-colors cursor-pointer group' : ''}`}>
        <div className={`w-2 h-2 rounded-full ${bgDot} animate-pulse`} />
        <div className="flex-1">
          <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider flex items-center gap-1">
            {label}
            {fyersSymbol && <span className="opacity-0 group-hover:opacity-100 transition-opacity text-blue-400">↗ chart</span>}
          </p>
          <p className="text-lg font-bold text-white tabular-nums tier-critical">{fmt(price)}</p>
          <p className={`text-xs font-medium ${textColor}`}>
            {arrow} {isPos ? '+' : ''}{fmt(change)} ({isPos ? '+' : ''}{fmt(changePercent)}%)
          </p>
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
      <Card label="NIFTY 50" price={nifty.price} change={nifty.change} changePercent={nifty.change_percent} fyersSymbol="NSE:NIFTY50-INDEX" sparklineData={niftyHistory} />
      <Card label="BANKNIFTY" price={bank.price} change={bank.change} changePercent={bank.change_percent} fyersSymbol="NSE:NIFTYBANK-INDEX" sparklineData={bankHistory} />
      
      {/* VIX */}
      <a href={fyersChartUrl("NSE:INDIAVIX-INDEX")} target="_blank" rel="noopener noreferrer" title="Open INDIA VIX chart on Fyers"
        className="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-800/60 border border-slate-700/50 hover:border-blue-500/50 hover:bg-slate-800/90 transition-colors cursor-pointer group">
        <div className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
        <div className="flex-1">
          <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider flex items-center gap-1">
            INDIA VIX
            <span className="opacity-0 group-hover:opacity-100 transition-opacity text-blue-400">↗ chart</span>
          </p>
          <p className="text-lg font-bold text-white tabular-nums tier-important">{fmt(vix.price || vix.value)}</p>
          <p className={`text-xs font-medium ${(vix.change || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {(vix.change || 0) >= 0 ? '↗ +' : '↘ '}{fmt(vix.change)}
          </p>
        </div>
        <Sparkline values={vixHistory} />
      </a>

      {/* PCR */}
      <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-800/60 border border-slate-700/50">
        <div className="w-2 h-2 rounded-full bg-purple-500 animate-pulse" />
        <div>
          <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">PCR</p>
          <p className="text-lg font-bold text-white tabular-nums tier-important">{pcr.value ? pcr.value.toFixed(2) : 'N/A'}</p>
          <p className="text-xs font-medium text-purple-400">{pcr.sentiment || 'N/A'}</p>
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
            <p className="text-lg font-bold text-white tabular-nums tier-critical">{fmt(crudePrice)}</p>
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
            <p className="text-lg font-bold text-white tabular-nums tier-critical">{fmt(crudePrice)}</p>
            <p className={`text-xs font-medium ${crudeIsPos ? 'text-emerald-400' : 'text-rose-400'}`}>
              {crudeChangePct != null ? `${crudeIsPos ? '↗ +' : '↘ '}${crudeChangePct.toFixed(2)}%` : '—'}
            </p>
          </div>
          <Sparkline values={crudeHistory} />
        </div>
      )}

      {/* Time */}
      <div className="hidden md:flex items-center justify-end px-4 py-3">
        <div className="text-right">
          <p className="text-xs text-slate-400 font-mono">
            {new Date(data.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
          </p>
          <p className="text-[10px] text-slate-500 font-mono">
            {new Date(data.timestamp).toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' })}
          </p>
          <p className="text-[10px] text-slate-600">Last updated</p>
        </div>
      </div>
    </div>
  );
}
