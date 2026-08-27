import { useEffect, useState } from 'react';

// Relative on purpose -- see the same note in SignalList.jsx. Routes
// through Vite's dev-server proxy so this works from any host the page
// was loaded from (localhost, home wifi, Tailscale) with no changes.
const API_BASE = import.meta.env.VITE_API_URL || '';

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
        // get_today_snapshots() already returns most-recent-first, so [0]
        // is the latest row -- null if nothing logged yet today.
        if (mounted) setCrudeRow((json.snapshots || [])[0] || null);
      } catch (err) {
        console.error('Crude oil fetch error:', err);
      }
    };
    fetchCrude();
    const interval = setInterval(fetchCrude, 30000);
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

  const Card = ({ label, price, change, changePercent, fyersSymbol }) => {
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
      <Card label="NIFTY 50" price={nifty.price} change={nifty.change} changePercent={nifty.change_percent} fyersSymbol="NSE:NIFTY50-INDEX" />
      <Card label="BANKNIFTY" price={bank.price} change={bank.change} changePercent={bank.change_percent} fyersSymbol="NSE:NIFTYBANK-INDEX" />
      
      {/* VIX */}
      <a href={fyersChartUrl("NSE:INDIAVIX-INDEX")} target="_blank" rel="noopener noreferrer" title="Open INDIA VIX chart on Fyers"
        className="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-800/60 border border-slate-700/50 hover:border-blue-500/50 hover:bg-slate-800/90 transition-colors cursor-pointer group">
        <div className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
        <div>
          <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider flex items-center gap-1">
            INDIA VIX
            <span className="opacity-0 group-hover:opacity-100 transition-opacity text-blue-400">↗ chart</span>
          </p>
          <p className="text-lg font-bold text-white tabular-nums tier-important">{fmt(vix.price || vix.value)}</p>
          <p className={`text-xs font-medium ${(vix.change || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {(vix.change || 0) >= 0 ? '↗ +' : '↘ '}{fmt(vix.change)}
          </p>
        </div>
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
          <div>
            <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider flex items-center gap-1">
              CRUDE OIL
              <span className="opacity-0 group-hover:opacity-100 transition-opacity text-blue-400">↗ chart</span>
            </p>
            <p className="text-lg font-bold text-white tabular-nums tier-critical">{fmt(crudePrice)}</p>
            <p className={`text-xs font-medium ${crudeIsPos ? 'text-emerald-400' : 'text-rose-400'}`}>
              {crudeChangePct != null ? `${crudeIsPos ? '↗ +' : '↘ '}${crudeChangePct.toFixed(2)}%` : '—'}
            </p>
          </div>
        </a>
      ) : (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-800/60 border border-slate-700/50">
          <div className={`w-2 h-2 rounded-full ${crudeIsPos ? 'bg-emerald-500' : 'bg-rose-500'} animate-pulse`} />
          <div>
            <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">CRUDE OIL</p>
            <p className="text-lg font-bold text-white tabular-nums tier-critical">{fmt(crudePrice)}</p>
            <p className={`text-xs font-medium ${crudeIsPos ? 'text-emerald-400' : 'text-rose-400'}`}>
              {crudeChangePct != null ? `${crudeIsPos ? '↗ +' : '↘ '}${crudeChangePct.toFixed(2)}%` : '—'}
            </p>
          </div>
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
