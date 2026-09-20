import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Sep 19 2026: fixed list of large-cap stocks -- deliberately NOT
// including NIFTY/BANKNIFTY here despite the reference watchlist
// showing them. Those are INDICES, and this view's own backend
// (WatchlistQuotesView) only reads _breadth_quote_cache/_stock_cache
// -- the STOCK caches Scanner/Market Pulse already keep warm -- not
// the separate index-quote path IndexCard.jsx/MarketBanner.jsx use.
// Adding indices here would mean either wiring a second data source
// into one view (scope creep on what was asked) or quietly always
// coming up empty for those two rows -- left out rather than shipped
// broken.
const DEFAULT_WATCHLIST = [
  'RELIANCE', 'HDFCBANK', 'ICICIBANK', 'INFY', 'TCS',
  'ITC', 'BHARTIARTL', 'LT', 'SBIN', 'KOTAKBANK', 'AXISBANK',
];

function fmtPrice(p) {
  if (p == null) return '—';
  return `₹${p.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}
function fmtPct(p) {
  if (p == null) return '—';
  return `${p >= 0 ? '+' : ''}${p.toFixed(2)}%`;
}

// Sep 19 2026: was a fixed-width side rail (w-64) sitting next to the
// chart -- that squeezed the chart itself narrower to make room for
// it, which is exactly the complaint. Redesigned as a horizontal
// strip that goes BELOW the chart instead, using the chart's own
// full width rather than competing with it for any.
export default function WatchlistRail({ activeSymbol, onSelect }) {
  const [quotes, setQuotes] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/api/watchlist-quotes/?symbols=${DEFAULT_WATCHLIST.join(',')}`)
      .then(r => r.json())
      .then(data => { if (!cancelled) setQuotes(data.quotes || []); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const covered = new Set(quotes.map(q => q.symbol));
  const missing = DEFAULT_WATCHLIST.filter(s => !covered.has(s));

  return (
    <div className="rounded-xl bg-slate-900/60 border border-slate-800 overflow-hidden">
      <div className="px-3 py-2.5 border-b border-slate-800">
        <span className="text-xs font-semibold text-slate-400 tracking-wide">WATCHLIST</span>
      </div>
      {loading && <div className="px-3 py-4 text-xs text-slate-500">Loading…</div>}
      {!loading && (
        <div className="flex gap-3 overflow-x-auto p-3">
          {quotes.map(q => {
            const positive = (q.change_percent || 0) >= 0;
            const active = q.symbol === activeSymbol;
            return (
              <button
                key={q.symbol}
                onClick={() => onSelect(q.symbol)}
                className={`shrink-0 w-40 text-left px-3 py-2 rounded-lg border transition-colors ${active ? 'bg-slate-800/80 border-emerald-500/40' : 'border-slate-800 hover:bg-slate-800/40 hover:border-slate-600'}`}
              >
                <div className="flex items-center justify-between">
                  <span className={`text-sm font-bold ${active ? 'text-emerald-400' : 'text-white'}`}>{q.symbol}</span>
                </div>
                <div className="text-sm text-slate-200 mt-0.5">{fmtPrice(q.price)}</div>
                <div className="flex items-center justify-between mt-0.5">
                  <span className="text-[10px] text-slate-500 truncate">{q.company_name || ''}</span>
                  <span className={`text-[11px] shrink-0 ml-1 ${positive ? 'text-emerald-400' : 'text-rose-400'}`}>{fmtPct(q.change_percent)}</span>
                </div>
              </button>
            );
          })}
        </div>
      )}
      {!loading && missing.length > 0 && (
        <div className="px-3 pb-2 text-[10px] text-slate-600">
          {missing.length} of {DEFAULT_WATCHLIST.length} not in this session's live cache yet: {missing.join(', ')}
        </div>
      )}
    </div>
  );
}
