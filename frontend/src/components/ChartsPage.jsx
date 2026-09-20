import { useState } from 'react';
import ChartCore from './ChartCore';
import WatchlistRail from './WatchlistRail';
import DrawingOverlay from './DrawingOverlay';

// Sep 19 2026: multi-pane + watchlist + drawing tools added, direct
// request. Each piece scoped to a real, working version rather than
// the reference's full depth -- see each piece's own comment for
// exactly what's simplified and why.
const QUICK_SYMBOLS = ['NIFTY', 'BANKNIFTY', 'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'SBIN'];
const PANE_COUNTS = [1, 2, 3, 4];
const DRAWING_TOOLS = [
  { id: 'none', label: '↖', title: 'Select (no drawing)' },
  { id: 'trendline', label: '📈', title: 'Trendline -- click two points' },
  { id: 'horizontal', label: '—', title: 'Horizontal line -- click once' },
];

function Pane({ symbol, priceHeight, tool }) {
  // Sep 19 2026: keyed by symbol at the pane-wrapper level (below) so
  // React remounts this whole pane -- and with it DrawingOverlay's
  // own local `drawings` state -- on a symbol change, rather than
  // needing extra plumbing to clear stale, now-mispositioned lines by
  // hand. Interval/range changes happen INSIDE ChartCore, invisible
  // to this wrapper, so drawings do NOT auto-clear on those -- a
  // real, stated limitation (see DrawingOverlay's own comment for
  // why: these are screen-space lines, not price/time-anchored ones).
  const [drawings, setDrawings] = useState([]);
  return (
    <div className="rounded-xl bg-slate-900/60 border border-slate-800 p-3">
      <ChartCore
        symbol={symbol}
        priceHeight={priceHeight}
        rsiHeight={90}
        priceOverlay={<DrawingOverlay tool={tool} drawings={drawings} setDrawings={setDrawings} />}
      />
    </div>
  );
}

export default function ChartsPage({ initialSymbol }) {
  const [paneCount, setPaneCount] = useState(1);
  const [panes, setPanes] = useState([initialSymbol || 'RELIANCE', 'NIFTY', 'BANKNIFTY', 'TCS']);
  const [activePane, setActivePane] = useState(0);
  const [searchInput, setSearchInput] = useState('');
  const [tool, setTool] = useState('none');

  const setPaneSymbol = (idx, symbol) => {
    setPanes((p) => { const next = [...p]; next[idx] = symbol; return next; });
  };
  const goToSymbol = (raw) => {
    const s = raw.trim().toUpperCase();
    if (s) setPaneSymbol(activePane, s);
    setSearchInput('');
  };

  const visiblePanes = panes.slice(0, paneCount);
  const gridCols = paneCount === 1 ? 'grid-cols-1' : 'grid-cols-1 lg:grid-cols-2';
  const priceHeight = paneCount === 1 ? 440 : 300;

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
            placeholder={`Search symbol for pane ${activePane + 1}…`}
            className="w-full pl-9 pr-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-slate-500 transition-colors"
          />
        </form>
        <div className="flex flex-wrap gap-1.5">
          {QUICK_SYMBOLS.map((s) => (
            <button
              key={s}
              onClick={() => setPaneSymbol(activePane, s)}
              className={`px-2.5 py-1.5 text-xs rounded-lg border transition-colors ${
                panes[activePane] === s
                  ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                  : 'text-slate-400 border-slate-700 hover:border-slate-500'
              }`}
            >
              {s}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1 ml-auto">
          <span className="text-[10px] text-slate-500 mr-1">PANES</span>
          {PANE_COUNTS.map((n) => (
            <button
              key={n}
              onClick={() => setPaneCount(n)}
              className={`w-7 h-7 text-xs rounded-lg border transition-colors ${
                paneCount === n
                  ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                  : 'text-slate-400 border-slate-700 hover:border-slate-500'
              }`}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-slate-500 mr-1">DRAW</span>
        {DRAWING_TOOLS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTool(t.id)}
            title={t.title}
            className={`px-2.5 py-1.5 text-xs rounded-lg border transition-colors ${
              tool === t.id
                ? 'bg-amber-500/15 text-amber-400 border-amber-500/30'
                : 'text-slate-400 border-slate-700 hover:border-slate-500'
            }`}
          >
            {t.label}
          </button>
        ))}
        {tool !== 'none' && <span className="text-[10px] text-slate-500 ml-1">Click the active pane's chart to draw · click a pane first to make it active</span>}
      </div>

      <div className={`grid ${gridCols} gap-4`}>
        {visiblePanes.map((symbol, idx) => (
          <div
            key={`pane-${idx}`}
            onClick={() => setActivePane(idx)}
            className={`rounded-xl transition-shadow ${activePane === idx ? 'ring-1 ring-emerald-500/40' : ''}`}
          >
            <Pane key={symbol} symbol={symbol} priceHeight={priceHeight} tool={activePane === idx ? tool : 'none'} />
          </div>
        ))}
      </div>

      <WatchlistRail activeSymbol={panes[activePane]} onSelect={(s) => setPaneSymbol(activePane, s)} />
    </div>
  );
}
