import { useState, useEffect, useRef, useCallback } from 'react';
import PatternChart from './PatternChart';

const API_BASE = import.meta.env.VITE_API_URL || '';

const UNIVERSES = [
  { key: 'nifty50', label: 'Nifty 50' },
  { key: 'nifty100', label: 'Nifty 100' },
  { key: 'nifty200', label: 'Nifty 200' },
  { key: 'fno', label: 'F&O' },
  { key: 'nifty500', label: 'Nifty 500' },
  { key: 'all', label: 'All stocks' },
];
const FAMILY_HINT = {
  Reversal: 'Reversal: the trend turns.',
  Continuation: 'Continuation: it pauses, then resumes.',
  Range: 'Range: price is boxed in a channel or rectangle.',
  'Curve & Cup': 'Curve & Cup: a rounded turn, with or without a handle.',
};
const DESCRIPTIONS = {
  'Double Top': 'Two peaks at a similar level with a dip between them. A close below the dip (the neckline) completes it; the target is the dip-to-peak height projected down.',
  'Double Bottom': 'Two lows at a similar level with a bounce between them. A close above the bounce (the neckline) completes it; the target is the bounce-to-low height projected up.',
  'Triple Top': 'Three failed attempts at the same ceiling. A close below the lower of the two dips completes it.',
  'Triple Bottom': 'Three holds at the same floor. A close above the higher of the two bounces completes it.',
  'Head & Shoulders': 'A higher peak (head) between two lower, similar peaks (shoulders). A close below the neckline joining the two dips completes it.',
  'Inverse Head & Shoulders': 'A deeper low (head) between two shallower, similar lows. A close above the neckline joining the two bounces completes it.',
  'Rising Wedge': 'Higher highs and higher lows inside two rising, converging lines. Usually resolves down, on a close below the lower line.',
  'Falling Wedge': 'Lower highs and lower lows inside two falling, converging lines. Usually resolves up, on a close above the upper line.',
  'Ascending Triangle': 'A flat ceiling tested repeatedly with rising lows. A close above the ceiling completes it.',
  'Descending Triangle': 'A flat floor tested repeatedly with falling highs. A close below the floor completes it.',
  'Symmetrical Triangle': 'Lower highs and higher lows squeezing toward an apex, in the direction of the prior trend.',
  'Bull Flag': 'A sharp rally (the pole) followed by a short, slightly down-sloping rest. A close above the flag completes it; the target is the pole height.',
  'Bear Flag': 'A sharp drop (the pole) followed by a short, slightly up-sloping rest. A close below the flag completes it; the target is the pole height.',
  'Bull Pennant': 'A sharp rally followed by a small converging triangle. A close above it completes it.',
  'Bear Pennant': 'A sharp drop followed by a small converging triangle. A close below it completes it.',
  Rectangle: 'Price bouncing between a flat floor and a flat ceiling. Bias follows the prior trend; a close outside the box resolves it.',
  'Ascending Channel': 'Two parallel rising lines containing price. No target or stop is drawn: it is a range, not a trigger.',
  'Descending Channel': 'Two parallel falling lines containing price. No target or stop is drawn: it is a range, not a trigger.',
  'Rounded Top': 'A gradual, symmetric rise and fall. A close below the rim (the lower of the two ends) completes it.',
  'Rounded Bottom': 'A gradual, symmetric fall and rise. A close above the rim (the higher of the two ends) completes it.',
  'Cup & Handle': 'A rounded bottom whose right rim stalls in a small pullback (the handle). A close above the rim completes it; the target is the cup depth.',
};

const fmtPrice = (p) => (p == null ? '—' : `₹${p.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`);
const ago = (n) => (n === 0 ? 'today' : `${n} daily candle${n === 1 ? '' : 's'} ago`);

const STATUS_CLS = {
  Confirmed: 'text-emerald-300 border-emerald-500/50 bg-emerald-500/10',
  Forming: 'text-slate-300 border-slate-600 bg-slate-800/60',
  Failed: 'text-rose-300 border-rose-500/50 bg-rose-500/10',
};
const QUALITY_CLS = { Textbook: 'text-emerald-300', Strong: 'text-sky-300', Fair: 'text-slate-400' };

function DirIcon({ direction }) {
  const cls = direction === 'Bullish' ? 'bg-emerald-500/15 text-emerald-400' : direction === 'Bearish' ? 'bg-rose-500/15 text-rose-400' : 'bg-slate-700/40 text-slate-400';
  return <span className={`inline-flex items-center justify-center w-5 h-5 rounded text-[11px] shrink-0 ${cls}`}>{direction === 'Bullish' ? '↗' : direction === 'Bearish' ? '↘' : '↔'}</span>;
}

function Chip({ active, onClick, children, count }) {
  return (
    <button onClick={onClick}
      className={`text-[11px] px-2.5 py-1 rounded-full border transition-colors ${active ? 'bg-emerald-500/20 border-emerald-500/60 text-emerald-300' : 'bg-slate-900/60 border-slate-700 text-slate-300 hover:border-slate-500'}`}>
      {children}{count != null && <span className="opacity-60"> {count}</span>}
    </button>
  );
}

function Levels({ p }) {
  const hasLevels = p.target != null && p.stop != null;
  return (
    <div className="grid grid-cols-3 gap-1.5 text-center">
      {[['Breakout', p.direction === 'Bearish' ? 'Breakdown' : 'Breakout', p.trigger, 'text-amber-400'], ['Target', 'Target', p.target, 'text-emerald-400'], ['Stop', 'Stop', p.stop, 'text-rose-400']].map(([k, label, val, cls]) => (
        <div key={k} className="rounded-lg bg-slate-800/50 border border-slate-700/60 py-1.5">
          <div className="text-[9px] tracking-wide text-slate-500 uppercase">{label}</div>
          <div className={`text-xs font-bold ${hasLevels || k === 'Breakout' ? cls : 'text-slate-500'}`}>{hasLevels || k === 'Breakout' ? fmtPrice(val) : '—'}</div>
        </div>
      ))}
    </div>
  );
}

function PatternCard({ p, selected, onSelect }) {
  return (
    <div onClick={() => onSelect(p)}
      className={`rounded-xl border p-3 cursor-pointer transition-colors bg-gradient-to-b from-slate-900/80 to-slate-900/40 ${selected ? 'border-emerald-500/60 shadow-lg shadow-emerald-500/5' : 'border-slate-800 hover:border-slate-600'}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="w-7 h-7 rounded-lg bg-slate-800 border border-slate-700 text-[10px] font-bold text-slate-300 flex items-center justify-center shrink-0">{p.symbol.slice(0, 2)}</span>
          <div className="min-w-0">
            <div className="text-xs font-bold text-white truncate">{p.symbol}</div>
            <div className="text-[10px] text-slate-500 truncate">{p.company}</div>
          </div>
        </div>
        <span className={`text-[10px] px-2 py-0.5 rounded-full border shrink-0 ${STATUS_CLS[p.status]}`}>{p.status}</span>
      </div>
      <div className="flex items-center gap-1.5 mt-2.5">
        <DirIcon direction={p.direction} />
        <span className="text-[12px] font-semibold text-slate-100 truncate">{p.name}{p.unresolved ? ' (unresolved range)' : ''}</span>
      </div>
      <div className="relative mt-2 aspect-[300/132] w-full rounded-lg bg-slate-950/50 border border-slate-800 overflow-hidden">
        <span className="absolute top-1 left-1.5 z-10 text-[9px] font-semibold text-slate-400 bg-slate-800/80 border border-slate-700 rounded px-1">1D</span>
        <PatternChart pattern={p} />
      </div>
      <div className="mt-2"><Levels p={p} /></div>
      <div className="flex items-center justify-between mt-2 text-[10px] text-slate-500">
        <span>⏱ {ago(p.bars_ago)}</span>
        <span>R:R <span className="text-slate-300 font-semibold">{p.rr != null ? `1 : ${p.rr}` : '—'}</span></span>
      </div>
      <div className="flex items-center justify-between mt-1 text-[10px]">
        <span className={`font-semibold ${QUALITY_CLS[p.quality]}`}>{p.quality}</span>
        <span className="text-slate-500">
          Close {fmtPrice(p.last_close)}
          {p.pct_vs_trigger != null && <span className="text-slate-400"> · {p.pct_vs_trigger >= 0 ? '+' : ''}{p.pct_vs_trigger}% vs trigger</span>}
        </span>
      </div>
    </div>
  );
}

function DetailPanel({ p, onOpenChart, baseline }) {
  if (!p) {
    return <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 text-center text-xs text-slate-500">Select a pattern card to see its chart, levels and how it is defined.</div>;
  }
  const stat = (label, value, sub) => (
    <div className="rounded-lg bg-slate-800/40 border border-slate-700/50 p-2">
      <div className="text-[9px] tracking-wide text-slate-500 uppercase">{label}</div>
      <div className="text-xs font-semibold text-white">{value}</div>
      {sub && <div className="text-[9px] text-slate-500">{sub}</div>}
    </div>
  );
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-bold text-white">{p.symbol}</div>
          <div className="text-[11px] text-slate-500 truncate">{p.company}</div>
        </div>
        <button onClick={() => onOpenChart(p.symbol)} className="text-[11px] px-2.5 py-1 rounded-lg border border-slate-600 text-slate-300 hover:border-slate-400 shrink-0">Stock page ↗</button>
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        {stat('Last close', fmtPrice(p.last_close), p.data_through)}
        {stat('Pattern spans', `${p.span_bars} candles`, '1D')}
        {stat('Sector', p.sector || '—')}
      </div>
      <div>
        <div className="flex items-center gap-1.5 flex-wrap">
          <DirIcon direction={p.direction} />
          <span className="text-sm font-bold text-white">{p.name}</span>
          <span className={`text-[10px] px-2 py-0.5 rounded-full border ${STATUS_CLS[p.status]}`}>{p.status}</span>
          <span className="text-[10px] px-2 py-0.5 rounded-full border border-slate-700 text-slate-400">{p.direction}</span>
        </div>
        <div className="mt-2 rounded-lg bg-slate-950/50 border border-slate-800 overflow-hidden" style={{ aspectRatio: '560 / 300' }}>
          <PatternChart pattern={p} large />
        </div>
      </div>
      <p className="text-[11px] leading-relaxed text-slate-400">{DESCRIPTIONS[p.name] || ''}</p>
      <Levels p={p} />
      <div className="grid grid-cols-2 gap-1.5">
        {stat('Completed', ago(p.bars_ago), p.end_date)}
        {stat('R:R', p.rr != null ? `1 : ${p.rr}` : '—', p.volume_confirmed ? 'breakout on ≥1.5× volume' : 'no volume confirmation')}
        {stat('Shape quality', <span className={QUALITY_CLS[p.quality]}>{p.quality} · {p.score}</span>, 'fit to the textbook shape — not a success rate')}
        {stat('Family', p.family)}
      </div>
      {baseline && (
        <p className="text-[10px] leading-relaxed text-slate-500 border-t border-slate-800 pt-2">
          Reality check: this detector also finds a Fair-or-better shape in {Math.round(baseline.fair_plus * 100)}% of <em>random-walk</em> charts
          ({Math.round(baseline.strong_plus * 100)}% Strong-or-better, {Math.round(baseline.textbook * 100)}% Textbook). These patterns have not been back-tested here.
          Treat a card as a chart worth looking at, not a signal.
        </p>
      )}
    </div>
  );
}

export default function ChartPatterns({ onOpenChart }) {
  const [universe, setUniverse] = useState(() => { try { return localStorage.getItem('fo-radar-pattern-universe') || 'nifty500'; } catch { return 'nifty500'; } });
  const [filters, setFilters] = useState({ family: null, direction: null, status: null, quality: null, within: null, volume: false, sort: 'composite', q: '' });
  const [data, setData] = useState(null);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [scanMsg, setScanMsg] = useState(null);
  const reqId = useRef(0);

  const setF = (patch) => setFilters((f) => ({ ...f, ...patch }));
  const toggle = (key, val) => setFilters((f) => ({ ...f, [key]: f[key] === val ? null : val }));

  const buildUrl = useCallback((offset) => {
    const p = new URLSearchParams({ universe, offset: String(offset), limit: '36', sort: filters.sort });
    if (filters.family) p.set('family', filters.family);
    if (filters.direction) p.set('direction', filters.direction);
    if (filters.status) p.set('status', filters.status);
    if (filters.quality) p.set('quality', filters.quality);
    if (filters.within) p.set('within', String(filters.within));
    if (filters.volume) p.set('volume', '1');
    if (filters.q.trim()) p.set('q', filters.q.trim());
    return `${API_BASE}/api/chart-patterns/?${p.toString()}`;
  }, [universe, filters]);

  const load = useCallback((silent) => {
    const id = ++reqId.current;
    if (!silent) { setLoading(true); setError(null); }
    return fetch(buildUrl(0))
      .then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then((json) => { if (id !== reqId.current) return; setData(json); setItems(json.patterns); setLoading(false); })
      .catch((e) => { if (id !== reqId.current) return; setError(e.message); setLoading(false); });
  }, [buildUrl]);

  // refetch (debounced) whenever the universe or any filter changes
  useEffect(() => {
    const t = setTimeout(() => load(false), filters.q ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, filters.q]);

  useEffect(() => { try { localStorage.setItem('fo-radar-pattern-universe', universe); } catch { /* ignore */ } setSelected(null); }, [universe]);

  const scanState = data?.scan?.state;
  const running = scanState === 'running';

  // while a scan runs, refresh status + list every few seconds so results stream in
  useEffect(() => {
    if (!running) return undefined;
    const t = setInterval(() => load(true), 5000);
    return () => clearInterval(t);
  }, [running, load]);

  const startScan = () => {
    setScanMsg(null);
    fetch(`${API_BASE}/api/chart-patterns/scan/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ universe }) })
      .then((r) => r.json().then((j) => ({ ok: r.ok, j })))
      .then(({ ok, j }) => { if (!ok) setScanMsg(j.reason || 'Could not start the scan.'); load(true); })
      .catch((e) => setScanMsg(e.message));
  };

  const loadMore = () => {
    setLoadingMore(true);
    fetch(buildUrl(items.length))
      .then((r) => r.json())
      .then((json) => setItems((prev) => [...prev, ...json.patterns.filter((p) => !prev.some((q) => q.id === p.id))]))
      .finally(() => setLoadingMore(false));
  };

  const scan = data?.scan || {};
  const fac = data?.facets || { family: {}, direction: {}, status: {}, quality: {} };
  const pct = scan.total ? Math.min(100, Math.round((scan.scanned / scan.total) * 100)) : 0;
  const q = filters.quality;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-bold text-white">Chart Patterns</h2>
        <span className="text-[11px] text-slate-500">Algorithmic detection on daily closes · structure, not advice</span>
      </div>

      {/* universe scan card */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] text-slate-400 font-semibold">Universe</span>
          {UNIVERSES.map((u) => (
            <button key={u.key} onClick={() => setUniverse(u.key)} disabled={running}
              className={`text-[11px] px-2.5 py-1 rounded-full border transition-colors disabled:opacity-50 ${universe === u.key ? 'bg-slate-100/10 border-slate-300/50 text-white' : 'bg-slate-900/60 border-slate-700 text-slate-300 hover:border-slate-500'}`}>
              {u.label}
            </button>
          ))}
          <div className="flex-1" />
          <button onClick={startScan} disabled={running}
            className="text-[11px] px-3 py-1.5 rounded-lg border border-slate-500 text-slate-100 hover:bg-slate-800 disabled:opacity-50 flex items-center gap-1.5">
            {running && <span className="inline-block w-2.5 h-2.5 rounded-full border border-slate-500 border-t-white animate-spin" />}
            {running ? 'Scanning…' : scanState === 'never' || !scanState ? 'Scan now' : 'Scan again'}
          </button>
        </div>
        {running && (
          <div>
            <div className="h-1.5 rounded bg-slate-800 overflow-hidden"><div className="h-full bg-emerald-500/70 transition-all" style={{ width: `${pct}%` }} /></div>
            <div className="text-[11px] text-slate-500 mt-1">Scanned {scan.scanned} of {scan.total} · {scan.with_patterns} with patterns · {scan.failed} failed to load · history is fetched one symbol at a time (paced), so a cold scan takes a few minutes</div>
          </div>
        )}
        {!running && scanState && scanState !== 'never' && (
          <div className="text-[11px] text-slate-500">
            Scanned {scan.scanned} of {scan.total} in {scan.elapsed_s}s · {scan.with_patterns} with patterns · {scan.failed} failed to load · {scan.skipped_short} skipped (under 60 daily candles) · price data through {scan.data_through || '—'}
            {scanState === 'partial' && <span className="text-amber-400"> · interrupted scan — results are partial</span>}
          </div>
        )}
        {scanState === 'never' && !running && (
          <div className="text-[11px] text-slate-500">No scan for this universe yet. Press <b>Scan now</b>: it pulls ~8 months of daily candles per stock from Fyers, then everything is detected locally.</div>
        )}
        {scanMsg && <div className="text-[11px] text-amber-400">{scanMsg}</div>}
      </div>

      {/* stat tiles */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
        {[
          ['Scanned', scan.scanned ?? 0, `of ${scan.total ?? data?.universe_size ?? 0} in universe`],
          ['Patterns', data?.all_patterns ?? 0, 'all ages'],
          ['In view', data?.total ?? 0, 'with current filters'],
          ['Confirmed', fac.status.Confirmed ?? 0, 'decisive close, held'],
          ['Bull / Bear', `${fac.direction.Bullish ?? 0} / ${fac.direction.Bearish ?? 0}`, 'resolved bias only'],
          ['Data through', scan.data_through || '—', 'newest daily candle'],
        ].map(([label, value, sub]) => (
          <div key={label} className="rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2">
            <div className="text-[9px] tracking-wide text-slate-500 uppercase">{label}</div>
            <div className="text-base font-bold text-white">{value}</div>
            <div className="text-[10px] text-slate-500">{sub}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_340px]">
        {/* filters */}
        <aside className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 space-y-4 self-start">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-white">Filters</span>
            <button onClick={() => setFilters({ family: null, direction: null, status: null, quality: null, within: null, volume: false, sort: filters.sort, q: '' })} className="text-[10px] text-slate-500 hover:text-slate-300">↺ Reset</button>
          </div>
          <input value={filters.q} onChange={(e) => setF({ q: e.target.value })} placeholder="Symbol or company"
            className="w-full px-2.5 py-1.5 rounded-lg bg-slate-950/60 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-slate-500" />
          <div>
            <div className="text-[9px] tracking-wide text-slate-500 uppercase mb-1.5">Pattern family</div>
            <div className="flex flex-wrap gap-1.5">
              {['Reversal', 'Continuation', 'Range', 'Curve & Cup'].map((f) => <Chip key={f} active={filters.family === f} onClick={() => toggle('family', f)} count={fac.family[f] ?? 0}>{f}</Chip>)}
            </div>
            <div className="text-[10px] text-slate-600 mt-1.5">{filters.family ? FAMILY_HINT[filters.family] : 'Reversal: the trend turns. Continuation: it pauses, then resumes.'}</div>
          </div>
          <div>
            <div className="text-[9px] tracking-wide text-slate-500 uppercase mb-1.5">Direction</div>
            <div className="flex gap-1.5">
              {['Bullish', 'Bearish'].map((d) => <Chip key={d} active={filters.direction === d} onClick={() => toggle('direction', d)} count={fac.direction[d] ?? 0}>{d}</Chip>)}
            </div>
          </div>
          <div>
            <div className="text-[9px] tracking-wide text-slate-500 uppercase mb-1.5">Timeframe</div>
            <div className="flex gap-1.5"><Chip active onClick={() => {}}>Daily</Chip></div>
            <div className="text-[10px] text-slate-600 mt-1">Weekly/monthly need multi-year history that isn’t fetched here.</div>
          </div>
          <div>
            <div className="text-[9px] tracking-wide text-slate-500 uppercase mb-1.5">Status</div>
            <div className="flex flex-wrap gap-1.5">
              {['Forming', 'Confirmed', 'Failed'].map((s) => <Chip key={s} active={filters.status === s} onClick={() => toggle('status', s)} count={fac.status[s] ?? 0}>{s}</Chip>)}
            </div>
            <div className="text-[10px] text-slate-600 mt-1.5">Confirmed = a decisive close beyond the trigger that still holds. Failed = it broke out, then slipped back (or hit the stop).</div>
          </div>
          <div>
            <div className="text-[9px] tracking-wide text-slate-500 uppercase mb-1.5">Shape quality</div>
            <div className="grid grid-cols-3 gap-1 rounded-lg bg-slate-950/50 border border-slate-800 p-1">
              {[[null, 'Any'], ['Strong', 'Strong+'], ['Textbook', 'Textbook']].map(([val, label]) => (
                <button key={label} onClick={() => setF({ quality: val })}
                  className={`text-[11px] py-1 rounded-md ${q === val ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'}`}>{label}</button>
              ))}
            </div>
            <div className="text-[10px] text-slate-600 mt-1.5">How closely the drawing matches the textbook definition. Not a success rate.</div>
          </div>
          <div>
            <div className="text-[9px] tracking-wide text-slate-500 uppercase mb-1.5">Completed within (candles)</div>
            <div className="flex gap-1.5">
              {[10, 30, 60].map((n) => <Chip key={n} active={filters.within === n} onClick={() => toggle('within', n)}>{n}</Chip>)}
              <Chip active={!filters.within} onClick={() => setF({ within: null })}>Any</Chip>
            </div>
          </div>
          <div>
            <div className="text-[9px] tracking-wide text-slate-500 uppercase mb-1.5">Only</div>
            <Chip active={filters.volume} onClick={() => setF({ volume: !filters.volume })}>Volume confirmed</Chip>
          </div>
        </aside>

        {/* results */}
        <section className="space-y-3 min-w-0">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="text-xs text-slate-400"><b className="text-white">{data?.total ?? 0}</b> patterns of {data?.all_patterns ?? 0}</div>
            <div className="flex rounded-lg border border-slate-700 overflow-hidden">
              {[['composite', 'Composite'], ['recent', 'Recent'], ['cleanest', 'Cleanest']].map(([k, label]) => (
                <button key={k} onClick={() => setF({ sort: k })} className={`text-[11px] px-3 py-1 ${filters.sort === k ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'}`}>{label}</button>
              ))}
            </div>
          </div>
          {loading && <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-3">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-72 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />)}</div>}
          {error && <div className="text-center text-rose-400 text-sm py-8">⚠ {error}</div>}
          {!loading && !error && items.length === 0 && (
            <div className="text-center text-slate-500 text-sm py-12">
              {data?.all_patterns ? 'No patterns match these filters.' : scanState === 'running' ? 'Scanning — patterns appear here as they are found.' : 'Nothing here yet — press “Scan now” above.'}
            </div>
          )}
          {!loading && !error && items.length > 0 && (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-3">
                {items.map((p) => <PatternCard key={p.id} p={p} selected={selected?.id === p.id} onSelect={setSelected} />)}
              </div>
              {items.length < (data?.total ?? 0) && (
                <div className="text-center">
                  <button onClick={loadMore} disabled={loadingMore} className="text-xs px-4 py-2 rounded-lg border border-slate-600 text-slate-300 hover:border-slate-400 disabled:opacity-50">
                    {loadingMore ? 'Loading…' : `Load more (${(data?.total ?? 0) - items.length} left)`}
                  </button>
                </div>
              )}
            </>
          )}
        </section>

        {/* detail */}
        <aside className="hidden xl:block self-start sticky top-2">
          <DetailPanel p={selected} onOpenChart={onOpenChart} baseline={data?.baseline} />
        </aside>
      </div>

      {/* below xl the detail panel sits under the grid when something is selected */}
      {selected && <div className="xl:hidden"><DetailPanel p={selected} onOpenChart={onOpenChart} baseline={data?.baseline} /></div>}
    </div>
  );
}
