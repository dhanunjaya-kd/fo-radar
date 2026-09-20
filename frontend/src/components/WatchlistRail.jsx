import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

function fmtPrice(p) {
  if (p == null) return '—';
  return `₹${p.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}
function fmtPct(p) {
  if (p == null) return '—';
  return `${p >= 0 ? '+' : ''}${p.toFixed(2)}%`;
}

// Sep 19 2026: was a fixed DEFAULT_WATCHLIST constant -- direct
// request, that's not a real watchlist, that's a hardcoded list. Now
// backed by UserWatchlistView (a small JSON file on the backend, same
// atomic-write pattern as the breadth cache snapshot) -- survives a
// server restart, not just a browser session. Exports refreshWatchlist
// as a window-level function so a card elsewhere (Scanner) can tell
// this rail "something changed, re-fetch" without needing shared
// React state lifted all the way up through App.jsx for what's a
// fairly self-contained feature.
export default function WatchlistRail({ activeSymbol, onSelect }) {
  const [quotes, setQuotes] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    fetch(`${API_BASE}/api/user-watchlist/`)
      .then(r => r.json())
      .then(data => setQuotes(data.quotes || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    window.__refreshWatchlistRail = load;
    return () => { delete window.__refreshWatchlistRail; };
  }, []);

  const remove = (e, symbol) => {
    e.stopPropagation();
    fetch(`${API_BASE}/api/user-watchlist/${symbol}/`, { method: 'DELETE' })
      .then(r => r.json())
      .then(data => setQuotes(data.quotes || []))
      .catch(() => {});
  };

  return (
    <div className="rounded-xl bg-slate-900/60 border border-slate-800 overflow-hidden">
      <div className="px-3 py-2.5 border-b border-slate-800">
        <span className="text-xs font-semibold text-slate-400 tracking-wide">WATCHLIST</span>
      </div>
      {loading && <div className="px-3 py-4 text-xs text-slate-500">Loading…</div>}
      {!loading && quotes.length === 0 && (
        <div className="px-3 py-4 text-xs text-slate-500">
          Nothing here yet — add a stock from Scanner (the ☆ on any card) to build your watchlist.
        </div>
      )}
      {!loading && quotes.length > 0 && (
        <div className="flex gap-3 overflow-x-auto p-3">
          {quotes.map(q => {
            const positive = (q.change_percent || 0) >= 0;
            const active = q.symbol === activeSymbol;
            return (
              <button
                key={q.symbol}
                onClick={() => onSelect(q.symbol)}
                className={`group relative shrink-0 w-40 text-left px-3 py-2 rounded-lg border transition-colors ${active ? 'bg-slate-800/80 border-emerald-500/40' : 'border-slate-800 hover:bg-slate-800/40 hover:border-slate-600'}`}
              >
                <button
                  onClick={(e) => remove(e, q.symbol)}
                  title="Remove from watchlist"
                  className="absolute top-1 right-1 w-4 h-4 flex items-center justify-center rounded-full text-slate-600 hover:text-rose-400 hover:bg-slate-900 opacity-0 group-hover:opacity-100 transition-opacity text-[10px]"
                >
                  ×
                </button>
                <span className={`text-sm font-bold ${active ? 'text-emerald-400' : 'text-white'}`}>{q.symbol}</span>
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
    </div>
  );
}
