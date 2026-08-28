import { useEffect, useRef, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Aug 28 2026: tested in isolation (test_search_matching.js) before
// this component was written -- exact match ranks above prefix match,
// which ranks above substring match, case-insensitive, results capped.
function searchMatches(query, symbols, tabs, { maxSymbols = 5, maxTabs = 4 } = {}) {
  const q = query.trim().toUpperCase();
  if (!q) return { symbolResults: [], tabResults: [] };

  const rankSymbol = (sym) => {
    const s = sym.toUpperCase();
    if (s === q) return 0;
    if (s.startsWith(q)) return 1;
    if (s.includes(q)) return 2;
    return null;
  };
  const symbolResults = symbols
    .map(sym => ({ symbol: sym, rank: rankSymbol(sym) }))
    .filter(r => r.rank !== null)
    .sort((a, b) => a.rank - b.rank || a.symbol.localeCompare(b.symbol))
    .slice(0, maxSymbols)
    .map(r => r.symbol);

  const rankTab = (label) => {
    const l = label.toUpperCase();
    if (l === q) return 0;
    if (l.startsWith(q)) return 1;
    if (l.includes(q)) return 2;
    return null;
  };
  const tabResults = tabs
    .map(t => ({ ...t, rank: rankTab(t.label) }))
    .filter(r => r.rank !== null)
    .sort((a, b) => a.rank - b.rank)
    .slice(0, maxTabs);

  return { symbolResults, tabResults };
}

const IconSearch = ({ size = 15 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
);

// Aug 28 2026: symbol results navigate to OI Analytics -- the closest
// existing view to a real "stock detail" page, since it already has
// its own per-symbol analytics (PCR, Max Pain, ATM IV, etc). HONEST
// LIMITATION: this does NOT auto-populate that tab's own search box --
// that component (Analytics.jsx or whatever renders OI Analytics)
// hasn't been seen, so auto-filling its search safely isn't possible
// without guessing at its internals. Selecting a stock here gets you
// to the right TAB in one click; you'd still type the symbol there
// once more. Worth revisiting once that component is shared.
export default function SearchBar({ tabs, onNavigate }) {
  const [query, setQuery] = useState('');
  const [symbols, setSymbols] = useState([]);
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    let mounted = true;
    fetch(`${API_BASE}/api/stocks/fo-list/`)
      .then(res => res.ok ? res.json() : { stocks: [] })
      .then(data => {
        if (mounted) setSymbols((data.stocks || []).map(s => s.symbol || s).filter(Boolean));
      })
      .catch(() => {}); // search just won't have symbol results -- not worth surfacing an error for
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    const handleKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        containerRef.current?.querySelector('input')?.focus();
        setOpen(true);
      }
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, []);

  const { symbolResults, tabResults } = searchMatches(query, symbols, tabs);
  const hasResults = symbolResults.length > 0 || tabResults.length > 0;

  const selectSymbol = (sym) => {
    setQuery('');
    setOpen(false);
    onNavigate('oi', sym); // second arg: honest limitation above -- lands on the tab, doesn't pre-fill its search
  };
  const selectTab = (tabId) => {
    setQuery('');
    setOpen(false);
    onNavigate(tabId);
  };

  return (
    <div ref={containerRef} className="relative w-full max-w-xs">
      <div className="flex items-center gap-2 bg-slate-900/60 border border-slate-700/50 rounded-lg px-3 py-1.5 focus-within:border-emerald-500/50">
        <IconSearch />
        <input
          type="text"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          placeholder="Search stocks, indices, pages..."
          className="bg-transparent text-sm text-white placeholder-slate-500 focus:outline-none flex-1 min-w-0"
        />
        <kbd className="hidden sm:inline text-[10px] text-slate-500 bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5">⌘K</kbd>
      </div>

      {open && query && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-slate-900 border border-slate-700 rounded-lg shadow-xl overflow-hidden z-50 max-h-80 overflow-y-auto">
          {!hasResults ? (
            <p className="text-xs text-slate-500 px-3 py-3 text-center">No matches for "{query}"</p>
          ) : (
            <>
              {symbolResults.length > 0 && (
                <div>
                  <p className="text-[9px] text-slate-500 uppercase tracking-wider px-3 pt-2 pb-1">Stocks</p>
                  {symbolResults.map(sym => (
                    <button key={sym} onClick={() => selectSymbol(sym)}
                      className="w-full text-left px-3 py-1.5 text-sm text-white hover:bg-slate-800 transition-colors">
                      {sym}
                    </button>
                  ))}
                </div>
              )}
              {tabResults.length > 0 && (
                <div>
                  <p className="text-[9px] text-slate-500 uppercase tracking-wider px-3 pt-2 pb-1">Pages</p>
                  {tabResults.map(t => (
                    <button key={t.id} onClick={() => selectTab(t.id)}
                      className="w-full text-left px-3 py-1.5 text-sm text-white hover:bg-slate-800 transition-colors">
                      {t.label}
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
