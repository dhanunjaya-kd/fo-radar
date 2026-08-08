import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

export default function MarketBanner() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

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

  const fmt = (n) => {
    if (n === null || n === undefined || isNaN(n)) return '0.00';
    return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  const fyersChartUrl = (symbol) =>
    `https://trade.fyers.in/popout_chart/index.html?symbol=${encodeURIComponent(symbol)}&resolution=5&theme=light`;

  const Card = ({ label, price, change, changePercent, fyersSymbol }) => {
    const isPos = (change || 0) >= 0;
    const arrow = isPos ? '↗' : '↘';
    const textColor = isPos ? 'text-emerald-400' : 'text-rose-400';
    const bgDot = isPos ? 'bg-emerald-500' : 'bg-rose-500';

    const inner = (
      <div className={`flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-800/60 border border-slate-700/50 ${fyersSymbol ? 'hover:border-blue-500/50 hover:bg-slate-800/90 transition-colors cursor-pointer group' : ''}`}>
        <div className={`w-2 h-2 rounded-full ${bgDot}`} />
        <div className="flex-1">
          <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider flex items-center gap-1">
            {label}
            {fyersSymbol && <span className="opacity-0 group-hover:opacity-100 transition-opacity text-blue-400">↗ chart</span>}
          </p>
          <p className="text-lg font-bold text-white tabular-nums">{fmt(price)}</p>
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

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
      <Card label="NIFTY 50" price={nifty.price} change={nifty.change} changePercent={nifty.change_percent} fyersSymbol="NSE:NIFTY50-INDEX" />
      <Card label="BANKNIFTY" price={bank.price} change={bank.change} changePercent={bank.change_percent} fyersSymbol="NSE:NIFTYBANK-INDEX" />
      
      {/* VIX */}
      <a href={fyersChartUrl("NSE:INDIAVIX-INDEX")} target="_blank" rel="noopener noreferrer" title="Open INDIA VIX chart on Fyers"
        className="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-800/60 border border-slate-700/50 hover:border-blue-500/50 hover:bg-slate-800/90 transition-colors cursor-pointer group">
        <div className="w-2 h-2 rounded-full bg-amber-500" />
        <div>
          <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider flex items-center gap-1">
            INDIA VIX
            <span className="opacity-0 group-hover:opacity-100 transition-opacity text-blue-400">↗ chart</span>
          </p>
          <p className="text-lg font-bold text-white tabular-nums">{fmt(vix.price || vix.value)}</p>
          <p className={`text-xs font-medium ${(vix.change || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {(vix.change || 0) >= 0 ? '↗ +' : '↘ '}{fmt(vix.change)}
          </p>
        </div>
      </a>

      {/* PCR */}
      <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-800/60 border border-slate-700/50">
        <div className="w-2 h-2 rounded-full bg-purple-500" />
        <div>
          <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">PCR</p>
          <p className="text-lg font-bold text-white tabular-nums">{pcr.value ? pcr.value.toFixed(2) : 'N/A'}</p>
          <p className="text-xs font-medium text-purple-400">{pcr.sentiment || 'N/A'}</p>
        </div>
      </div>

      {/* Time */}
      <div className="hidden md:flex items-center justify-end px-4 py-3">
        <div className="text-right">
          <p className="text-xs text-slate-400 font-mono">
            {new Date(data.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
          </p>
          <p className="text-[10px] text-slate-600">Last updated</p>
        </div>
      </div>
    </div>
  );
}