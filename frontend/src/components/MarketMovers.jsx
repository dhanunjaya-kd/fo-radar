import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

export default function MarketMovers() {
  const [tab, setTab] = useState('gainers');
  const [movers, setMovers] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/market-summary/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (mounted) setMovers(json.movers || { gainers: [], losers: [] });
      } catch (err) {
        console.error('Market movers fetch error:', err);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (loading) {
    return <div className="h-64 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />;
  }

  const list = movers ? movers[tab] : [];

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/40">
        <h3 className="text-sm font-bold text-white">Market Movers</h3>
        <div className="flex gap-1 bg-slate-900/50 p-0.5 rounded-lg">
          {['gainers', 'losers'].map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`text-[11px] font-medium px-2.5 py-1 rounded-md transition-colors capitalize ${
                tab === t ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {list.length === 0 ? (
        <div className="p-6 text-center">
          <p className="text-sm text-slate-500">No {tab} right now.</p>
        </div>
      ) : (
        <div className="divide-y divide-slate-700/20">
          {list.map((m) => {
            const isPos = m.change_percent >= 0;
            return (
              <div key={m.symbol} className="flex items-center justify-between px-4 py-2.5 hover:bg-slate-900/30">
                <span className="text-sm text-white font-medium">{m.symbol}</span>
                <div className="flex items-center gap-3">
                  <span className="text-sm text-slate-300 tabular-nums">₹{m.price.toLocaleString('en-IN')}</span>
                  <span className={`text-sm font-bold tabular-nums w-16 text-right ${isPos ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {isPos ? '+' : ''}{m.change_percent.toFixed(2)}%
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
