import { useEffect, useState } from 'react';
import TabInfoBanner from './TabInfoBanner';

// Relative on purpose -- see the same note in SignalList.jsx / IndexTracker.jsx.
const API_BASE = import.meta.env.VITE_API_URL || '';

function fmt(n, digits = 2) {
  if (n == null || isNaN(n)) return '—';
  return Number(n).toLocaleString('en-IN', { maximumFractionDigits: digits });
}

export default function FundamentalsWatchlist() {
  const [stocks, setStocks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch(`${API_BASE}/api/fundamentals-watchlist/`)
        .then(r => r.json())
        .then(data => {
          if (cancelled) return;
          setStocks(data.watchlist || []);
          setError(null);
        })
        .catch(e => { if (!cancelled) setError(e.message); })
        .finally(() => { if (!cancelled) setLoading(false); });
    };
    load();
    // 5 min -- the underlying data only grows as the background
    // runner.py process progresses, no need to poll faster than that.
    const interval = setInterval(load, 300000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  if (loading) {
    return <div className="p-10 text-center text-slate-500 text-sm">Loading watchlist...</div>;
  }
  if (error) {
    return <div className="p-10 text-center text-slate-500 text-sm">Couldn't load watchlist: {error}</div>;
  }

  return (
    <div className="space-y-4">
      <TabInfoBanner>
        Long-term value candidates: NSE stocks meaningfully below their 52-week high, ranked by combined
        fundamentals (P/E, ROE, Debt/Equity, Sales growth) via percentile ranking — not a single opaque
        score, every input is shown in the table below. This list grows as background data collection
        progresses across the full NSE list; a short list right now just means it hasn't gotten there yet,
        not that nothing else qualifies. Not investment advice — a shortlist worth a closer look, not a verdict.
      </TabInfoBanner>

      {stocks.length === 0 ? (
        <div className="py-10 text-center text-slate-500 text-sm max-w-md mx-auto">
          No candidates yet. Either background data collection hasn't reached enough stocks so far, or none
          of what's been checked qualifies (meaningfully below its 52-week high, with usable fundamentals).
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-xs sm:text-sm">
            <thead>
              <tr className="bg-slate-900/60 text-slate-500 text-[11px] uppercase tracking-wide">
                <th className="text-left px-3 py-2.5 font-medium">Symbol</th>
                <th className="text-right px-3 py-2.5 font-medium">Price</th>
                <th className="text-right px-3 py-2.5 font-medium">Off 52w High</th>
                <th className="text-right px-3 py-2.5 font-medium">P/E</th>
                <th className="text-right px-3 py-2.5 font-medium">ROE</th>
                <th className="text-right px-3 py-2.5 font-medium">D/E</th>
                <th className="text-right px-3 py-2.5 font-medium">Sales CAGR</th>
                <th className="text-right px-3 py-2.5 font-medium">Rank</th>
              </tr>
            </thead>
            <tbody>
              {stocks.map((s, i) => (
                <tr key={s.symbol} className={`border-t border-slate-800/60 hover:bg-slate-900/40 transition-colors ${i === 0 ? 'bg-slate-900/30' : ''}`}>
                  <td className="px-3 py-2.5">
                    <div className="font-semibold text-sky-400 whitespace-nowrap">{s.symbol.replace('NSE:', '').replace('-EQ', '')}</div>
                    <div className="text-[11px] text-slate-500 truncate max-w-[160px]">{s.company_name}</div>
                  </td>
                  <td className="px-3 py-2.5 text-right text-white whitespace-nowrap">₹{fmt(s.current_price)}</td>
                  <td className="px-3 py-2.5 text-right text-rose-400 whitespace-nowrap">{fmt(s.pct_off_52w_high, 1)}%</td>
                  <td className="px-3 py-2.5 text-right text-slate-300 whitespace-nowrap">{s.pe_ratio != null ? fmt(s.pe_ratio) : '—'}</td>
                  <td className={`px-3 py-2.5 text-right whitespace-nowrap ${(s.roe_pct || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{fmt(s.roe_pct, 1)}%</td>
                  <td className="px-3 py-2.5 text-right text-slate-300 whitespace-nowrap">{fmt(s.debt_to_equity, 2)}</td>
                  <td className={`px-3 py-2.5 text-right whitespace-nowrap ${(s.sales_cagr_pct || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{s.sales_cagr_pct != null ? `${fmt(s.sales_cagr_pct, 1)}%` : '—'}</td>
                  <td className="px-3 py-2.5 text-right font-semibold text-indigo-400 whitespace-nowrap">{fmt(s.combined_fundamentals_rank, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
