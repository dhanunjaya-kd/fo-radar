import { useState } from 'react';
import ChartCore from './ChartCore';

// Sep 19 2026: direct request -- charts should open as their own
// full page (matching the reference's separate "Charts" nav item),
// not a small popup. This is the honest, achievable slice of that
// request: a real full-page chart with its own symbol search, using
// the exact same ChartCore the popup modal uses (candles, EMA 10/20/
// 50/200, RSI). The reference's own Charts page is a full multi-pane
// terminal -- a watchlist rail, ~16 indicator types, drawing tools,
// multi-pane layouts, a top quick-symbol bar -- each a genuinely
// separate, large build in its own right, not included here. This
// page is a real foundation to add those onto next, not a stand-in
// for them.
const QUICK_SYMBOLS = ['NIFTY', 'BANKNIFTY', 'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'SBIN'];

export default function ChartsPage({ initialSymbol }) {
  const [symbol, setSymbol] = useState(initialSymbol || 'RELIANCE');
  const [searchInput, setSearchInput] = useState('');

  const goToSymbol = (raw) => {
    const s = raw.trim().toUpperCase();
    if (s) setSymbol(s);
    setSearchInput('');
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-bold text-white shrink-0">Charts</h2>
        <form
          onSubmit={(e) => { e.preventDefault(); goToSymbol(searchInput); }}
          className="relative flex-1 min-w-[220px] max-w-sm"
        >
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-sm">🔍</span>
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search symbol…"
            className="w-full pl-9 pr-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-slate-500 transition-colors"
          />
        </form>
        <div className="flex flex-wrap gap-1.5">
          {QUICK_SYMBOLS.map((s) => (
            <button
              key={s}
              onClick={() => goToSymbol(s)}
              className={`px-2.5 py-1.5 text-xs rounded-lg border transition-colors ${
                symbol === s
                  ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                  : 'text-slate-400 border-slate-700 hover:border-slate-500'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-xl bg-slate-900/60 border border-slate-800 p-5">
        <ChartCore symbol={symbol} priceHeight={440} rsiHeight={140} />
      </div>
    </div>
  );
}
