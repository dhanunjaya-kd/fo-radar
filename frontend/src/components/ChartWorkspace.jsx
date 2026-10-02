import { useState, useEffect } from 'react';
import StockChart from './StockChart';

// Oct 2 2026: the research page's chart area -- the stock being researched in pane 1, plus up to three more
// panes to compare it against (an index, a peer, a sector leader) side by side. This replaces the old
// stand-alone Charts tab's multi-pane view; each pane is a full StockChart with its own timeframe and
// indicator strips.
const QUICK = ['NIFTY', 'BANKNIFTY', 'SENSEX'];
const PANE_KEY = 'fo-radar-chart-panes';

function ComparePane({ symbol, onChange, index }) {
  const [input, setInput] = useState('');
  const go = (raw) => { const s = raw.trim().toUpperCase().replace(/[^A-Z0-9&-]/g, ''); if (s) onChange(s); setInput(''); };
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-1.5 px-1">
        <span className="text-[10px] text-slate-500 uppercase tracking-wide">Pane {index + 2}</span>
        <form onSubmit={(e) => { e.preventDefault(); go(input); }} className="flex">
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="symbol, Enter"
            className="w-32 px-2 py-1 rounded-l-lg bg-slate-950/60 border border-slate-700/50 text-[11px] text-white placeholder-slate-600 focus:outline-none focus:border-slate-500" />
          <button type="submit" className="px-2 py-1 rounded-r-lg border border-l-0 border-slate-700/50 text-[11px] text-slate-300 hover:text-white">Go</button>
        </form>
        {QUICK.map((q) => (
          <button key={q} onClick={() => onChange(q)}
            className={`px-2 py-1 text-[10px] rounded-lg border ${symbol === q ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' : 'text-slate-400 border-slate-700 hover:border-slate-500'}`}>{q}</button>
        ))}
      </div>
      <StockChart key={symbol} symbol={symbol} compact />
    </div>
  );
}

export default function ChartWorkspace({ symbol }) {
  const [paneCount, setPaneCount] = useState(() => {
    try { const n = Number(localStorage.getItem(PANE_KEY)); return n >= 1 && n <= 4 ? n : 1; } catch { return 1; }
  });
  const [others, setOthers] = useState(['NIFTY', 'BANKNIFTY', 'SENSEX']);
  useEffect(() => { try { localStorage.setItem(PANE_KEY, String(paneCount)); } catch { /* storage blocked */ } }, [paneCount]);

  if (!symbol) return null;
  const setOther = (i, sym) => setOthers((o) => o.map((x, k) => (k === i ? sym : x)));

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-end gap-1">
        <span className="text-[10px] text-slate-500 mr-1 uppercase tracking-wide" title="Chart panes: compare the stock with an index or a peer side by side">Panes</span>
        {[1, 2, 3, 4].map((n) => (
          <button key={n} onClick={() => setPaneCount(n)}
            className={`w-7 h-7 text-xs rounded-lg border transition-colors ${paneCount === n ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' : 'text-slate-400 border-slate-700 hover:border-slate-500'}`}>{n}</button>
        ))}
      </div>
      <div className={`grid gap-3 ${paneCount === 1 ? 'grid-cols-1' : 'grid-cols-1 xl:grid-cols-2'}`}>
        <div className="space-y-1.5">
          {paneCount > 1 && <div className="flex items-center gap-1.5 px-1 h-[26px]"><span className="text-[10px] text-slate-500 uppercase tracking-wide">Pane 1 · researched stock</span></div>}
          <StockChart key={symbol} symbol={symbol} compact={paneCount > 1} />
        </div>
        {others.slice(0, paneCount - 1).map((sym, i) => (
          <ComparePane key={i} index={i} symbol={sym} onChange={(s) => setOther(i, s)} />
        ))}
      </div>
    </div>
  );
}
