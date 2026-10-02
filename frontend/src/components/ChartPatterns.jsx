import { useState, useEffect, useRef, useCallback } from 'react';
import PatternChart, { legendFor } from './PatternChart';
import { useTheme } from './ThemeContext';

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
const QUALITY_CLS = { Textbook: 'text-emerald-300', Strong: 'text-sky-300', Fair: 'text-slate-400', Weak: 'text-amber-400' };

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
        <div key={k} className="rounded-lg bg-slate-800/50 border border-slate-700/60 py-1.5 px-0.5 min-w-0">
          <div className="text-[9px] tracking-wide text-slate-500 uppercase">{label}</div>
          <div className={`text-[10.5px] font-bold tabular-nums ${hasLevels || k === 'Breakout' ? cls : 'text-slate-500'}`}>{hasLevels || k === 'Breakout' ? fmtPrice(val) : '—'}</div>
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
      <div className="flex items-center justify-between gap-2 mt-1 text-[10px]">
        <span className={`font-semibold shrink-0 ${QUALITY_CLS[p.quality]}`}>{p.quality}</span>
        <span className="text-slate-500 text-right min-w-0">
          Close {fmtPrice(p.last_close)}
          {p.pct_vs_trigger != null && <span className="text-slate-400"> · {p.pct_vs_trigger >= 0 ? '+' : ''}{p.pct_vs_trigger}% vs trigger</span>}
        </span>
      </div>
    </div>
  );
}

const STOP_RULE = {
  'Double Top': 'above the tops + 0.25 ATR', 'Double Bottom': 'below the lows − 0.25 ATR',
  'Triple Top': 'above the tops + 0.25 ATR', 'Triple Bottom': 'below the lows − 0.25 ATR',
  'Head & Shoulders': 'above the right shoulder + 0.25 ATR', 'Inverse Head & Shoulders': 'below the right shoulder − 0.25 ATR',
  'Rectangle': 'the opposite side of the box ± 0.25 ATR',
  'Bull Flag': 'below the flag + 0.25 ATR', 'Bear Flag': 'above the flag + 0.25 ATR',
  'Bull Pennant': 'below the pennant + 0.25 ATR', 'Bear Pennant': 'above the pennant + 0.25 ATR',
  'Rounded Top': 'above the apex + 0.25 ATR', 'Rounded Bottom': 'below the apex − 0.25 ATR',
  'Cup & Handle': 'below the handle low − 0.25 ATR',
};
const STOP_RULE_DEFAULT = 'beyond the far trendline, at least 1 ATR (and 35% of the pattern width) from the trigger';
const TARGET_RULE = {
  'Bull Flag': 'pole height', 'Bear Flag': 'pole height', 'Bull Pennant': 'pole height', 'Bear Pennant': 'pole height',
  'Cup & Handle': 'cup depth', 'Rounded Top': 'curve height', 'Rounded Bottom': 'curve height',
};

function familyBlurb(p) {
  const lead = p.prior_trend === 'up' ? 'up' : p.prior_trend === 'down' ? 'down' : null;
  if (p.family === 'Reversal') return lead ? `Price was moving ${lead} into this pattern, and it points the other way. It is a turn against that move.` : 'It points against the move that led into it: a turn, not a pause.';
  if (p.family === 'Continuation') return lead ? `Price was moving ${lead} into this pattern, and it points the same way: the move pauses, then resumes.` : 'It points the same way as the move that led into it: a pause, then a resume.';
  if (p.family === 'Range') return 'Price is boxed inside a channel or range. No trend is being claimed: it only matters if price leaves the box.';
  return 'A rounded turn rather than a sharp one — price curves from one side to the other.';
}

function whyItReads(p) {
  if (p.status === 'Forming' || p.broke_date == null) {
    return p.trigger != null ? `No decisive close beyond ${fmtPrice(p.trigger)} yet — it is still forming. ${p.direction === 'Bearish' ? 'A daily close below' : 'A daily close above'} that level, by at least 0.15 ATR, would confirm it.` : 'It is a range with no trigger: it only matters if price leaves the box.';
  }
  const dir = p.direction === 'Bearish' ? 'below' : 'above';
  const vol = p.volume_confirmed ? 'on above-average volume' : 'on ordinary volume';
  if (p.status === 'Confirmed') {
    return `Price closed decisively beyond the level, stayed beyond it ${p.bars_since_break > 0 ? 'in the bars after' : 'on the latest close'}, ${p.volume_confirmed ? 'and volume expanded on the break' : 'but volume did not expand on the break'}. Closed ${dir} ${fmtPrice(p.trigger)}, on ${p.broke_date}, ${vol}${p.bars_since_break > 0 ? ', and held for the sessions right after' : ''}.`;
  }
  return `Price broke ${dir} ${fmtPrice(p.trigger)} on ${p.broke_date}, ${vol}, but has since closed back inside (or hit the stop), so the pattern is marked Failed.`;
}

function pastText(x) {
  const res = x.outcome === 'target' ? `reached its target in ${x.bars} sessions` : x.outcome === 'stop' ? `hit its stop after ${x.bars} sessions` : 'did neither within 40 sessions';
  return `${x.break_date} · ${x.name} (${x.direction}) — ${res}`;
}

function BaseRates({ p, rates, universeLabel }) {
  const own = rates?.[`${p.name}|${p.direction}`];
  const fam = rates?.[`family:${p.family}|${p.direction}`];
  const MIN_N = 15;
  const r = own && own.n >= MIN_N ? own : fam && fam.n >= MIN_N ? fam : null;
  const scope = r === own ? `${r.n} confirmed ${p.name} (${p.direction.toLowerCase()}) breaks` : r ? `${r.n} confirmed ${p.family.toLowerCase()} ${p.direction.toLowerCase()} breaks (all pattern types — too few of this exact one)` : null;
  const pct = (v) => `${Math.round(v * 100)}%`;
  if (!r) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-2.5 text-[11px] text-slate-500">
        Not enough comparable breaks in this scan to quote a rate{own ? ` (only ${own.n} ${p.name} so far)` : ''}. Rates come from this app’s own scans (about a year of daily candles per stock) and need at least {MIN_N} instances; scan a bigger universe such as Nifty 500 to build the sample.
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-4 gap-1.5">
        {[['Hit target', pct(r.hit_target), `before stop · ${r.horizon} sessions`], ['Hit 2× height', pct(r.double), 'ran twice the pattern height'],
          ['Typical time', r.median_bars_to_target != null ? `~${r.median_bars_to_target}` : '—', 'sessions to target'], ['Stopped first', pct(r.hit_stop), 'touched the stop first']].map(([k, v, sub]) => (
          <div key={k} className="rounded-lg bg-slate-800/40 border border-slate-700/50 p-2">
            <div className="text-[9px] tracking-wide text-slate-500 uppercase leading-tight">{k}</div>
            <div className="text-sm font-bold text-white">{v}</div>
            <div className="text-[9px] text-slate-500 leading-tight">{sub}</div>
          </div>
        ))}
      </div>
      <p className="text-[10px] leading-relaxed text-slate-500">
        {pct(r.pullback)} pulled back to the breakout level within 10 sessions, so a retest is normal rather than a failed break. Based on {scope} found in {universeLabel} over roughly the last year,
        measured walk-forward without hindsight (entry at the close of the break bar), gross of costs. A small, one-regime sample — not a forecast for this stock.
      </p>
    </div>
  );
}

function DetailPanel({ p, onOpenStock, baseline, rates, universeLabel, embedded = false }) {
  const light = useTheme().theme === 'light';
  if (!p) {
    return <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 text-center text-xs text-slate-500">Select a pattern card to see its chart, levels, how it is defined and how similar breaks played out.</div>;
  }
  const stat = (label, value, sub) => (
    <div className="rounded-lg bg-slate-800/40 border border-slate-700/50 p-2 min-w-0">
      <div className="text-[9px] tracking-wide text-slate-500 uppercase">{label}</div>
      <div className="text-xs font-semibold text-white break-words">{value}</div>
      {sub && <div className="text-[9px] text-slate-500 break-words">{sub}</div>}
    </div>
  );
  const bear = p.direction === 'Bearish';
  const yrs = p.history_bars ? (p.history_bars / 250).toFixed(1) : null;
  const legend = legendFor(p, light);
  const hasLevels = p.target != null && p.stop != null;
  const volLine = p.broke_date == null ? 'Not broken out yet' : p.volume_confirmed ? 'Broke out on above-average volume' : 'No volume expansion on the break';
  const pctTxt = p.pct_vs_trigger != null ? `${p.pct_vs_trigger >= 0 ? '+' : '−'}${Math.abs(p.pct_vs_trigger).toFixed(1)}% vs ${bear ? 'breakdown' : 'breakout'}` : '';
  const title = p.direction === 'Neutral' ? p.name : `${p.direction} ${p.name}`;
  return (
    <div className={embedded ? 'space-y-3' : 'rounded-xl border border-slate-800 bg-slate-900/50 p-3 space-y-3 max-h-[calc(100vh-1rem)] overflow-y-auto'}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="w-9 h-9 rounded-lg bg-slate-800 border border-slate-700 text-[11px] font-bold text-slate-300 flex items-center justify-center shrink-0">{p.symbol.slice(0, 2)}</span>
          <div className="min-w-0">
            <div className="text-sm font-bold text-white">{p.symbol}</div>
            <div className="text-[11px] text-slate-500 truncate">{p.company}</div>
          </div>
        </div>
        <button onClick={() => onOpenStock && onOpenStock(p.symbol)} title="Open the stock's research page: price chart plus fundamentals" className="text-[11px] px-2.5 py-1 rounded-lg border border-sky-500/40 bg-sky-500/10 text-sky-300 hover:bg-sky-500/20 shrink-0">Stock page ↗</button>
      </div>

      <div className="grid grid-cols-3 gap-1.5">
        {stat('Last close', fmtPrice(p.last_close), p.data_through)}
        {stat('History', yrs ? `${yrs}y` : '—', `${p.history_bars || '—'} daily candles`)}
        {stat('Patterns', p.stock?.patterns ?? '—', 'in this scan')}
        {stat('Confirmed', <span className="text-emerald-400">{p.stock?.confirmed ?? '—'}</span>, 'held the break')}
        {stat('Forming', p.stock?.forming ?? '—', 'not yet broken out')}
        {stat('Timeframe', 'Daily', 'only')}
      </div>

      <div>
        <div className="flex items-center gap-1.5 flex-wrap">
          <DirIcon direction={p.direction} />
          <span className="text-sm font-bold text-white">{title}{p.unresolved ? ' (unresolved range)' : ''}</span>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap mt-1.5">
          <span className="text-[10px] px-2 py-0.5 rounded-full border border-slate-700 text-slate-400">{p.direction}</span>
          <span className="text-[10px] px-2 py-0.5 rounded-full border border-slate-700 text-slate-400">1D</span>
          <span className={`text-[10px] px-2 py-0.5 rounded-full border ${STATUS_CLS[p.status]}`}>{p.status}</span>
          {p.below_bar && <span className="text-[10px] px-2 py-0.5 rounded-full border border-amber-500/50 text-amber-300 bg-amber-500/10">Below the quality bar</span>}
        </div>
        <div className="mt-2 rounded-lg bg-slate-950/50 border border-slate-800 overflow-hidden" style={{ aspectRatio: '600 / 330' }}>
          <PatternChart pattern={p} large />
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2">
          {legend.map((it) => (
            <span key={it.label} className="inline-flex items-center gap-1.5 text-[10px] text-slate-400">
              <svg width="18" height="6"><line x1="0" y1="3" x2="18" y2="3" stroke={it.color} strokeWidth="2" strokeDasharray={it.dash || undefined} /></svg>{it.label}
            </span>
          ))}
        </div>
        <p className="text-[10px] text-slate-600 mt-1">Lines are fitted through swing highs and lows (the candle wicks) — judged by the detector, not drawn by hand.</p>
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        {stat('Completed', ago(p.bars_ago), p.end_date)}
        {stat('Spans', `${p.span_bars} daily candles`)}
        {stat('Broke out', p.broke_date ? (p.bars_since_break === 0 ? 'on the latest candle' : `${p.bars_since_break} daily candle${p.bars_since_break === 1 ? '' : 's'} ago`) : 'Not yet', p.broke_date)}
        {stat('Last close', `${fmtPrice(p.last_close)}`, pctTxt)}
        {stat('Shape quality', <span className={QUALITY_CLS[p.quality]}>{p.quality} · {p.score}</span>, '(not a success rate)')}
        {stat('Volume', volLine)}
      </div>

      <div>
        <div className="text-[9px] tracking-wide text-slate-500 uppercase mb-1">{p.family}</div>
        <p className="text-[11px] leading-relaxed text-slate-300">{familyBlurb(p)}</p>
      </div>

      <div>
        <div className="grid grid-cols-4 gap-1.5 text-center">
          {[[bear ? 'Breakdown' : 'Breakout', p.trigger, 'text-amber-400', bear ? 'close below' : 'close above', true],
            ['Target', p.target, 'text-emerald-400', TARGET_RULE[p.name] || 'measured move', hasLevels],
            ['Stop', p.stop, 'text-rose-400', 'family rule', hasLevels],
            ['R : R', p.rr != null ? `1 : ${p.rr}` : null, 'text-slate-200', 'geometry only', hasLevels]].map(([k, v, cls, sub, show]) => (
            <div key={k} className="rounded-lg bg-slate-800/50 border border-slate-700/60 py-1.5 px-1">
              <div className="text-[9px] tracking-wide text-slate-500 uppercase">{k}</div>
              <div className={`text-xs font-bold ${show ? cls : 'text-slate-500'}`}>{show && v != null ? (typeof v === 'number' ? fmtPrice(v) : v) : '—'}</div>
              <div className="text-[9px] text-slate-500">{show ? sub : ''}</div>
            </div>
          ))}
        </div>
        <p className="text-[10px] leading-relaxed text-slate-500 mt-1.5">
          Levels are the detector’s own output as of {p.data_through || 'the latest candle'} — not a live price and not a recommendation. R:R describes the structure’s geometry, not a fill.
          {hasLevels && ` Stop: ${STOP_RULE[p.name] || STOP_RULE_DEFAULT}; never closer than 1 ATR to the trigger.`}
          {!hasLevels && ' Channels are ranges, so no target or stop is drawn.'}
        </p>
      </div>

      <div>
        <div className="text-[9px] tracking-wide text-slate-500 uppercase mb-1">Why it reads this way</div>
        <p className="text-[11px] leading-relaxed text-slate-400">{DESCRIPTIONS[p.name] || ''}</p>
        <p className="text-[11px] leading-relaxed text-slate-300 mt-1.5">{whyItReads(p)}</p>
      </div>

      {p.confluence && p.confluence.length > 0 && (
        <div>
          <div className="text-[9px] tracking-wide text-slate-500 uppercase mb-1">Confluence · candle {p.broke_date ? 'on the break' : 'today'}</div>
          <div className="flex flex-wrap gap-1.5">{p.confluence.map((c) => <span key={c} className="text-[10px] px-2 py-0.5 rounded-full border border-slate-700 text-slate-300">{c}</span>)}</div>
        </div>
      )}

      <div>
        <div className="text-[9px] tracking-wide text-slate-500 uppercase mb-1">What usually happens next · base rates</div>
        <BaseRates p={p} rates={rates} universeLabel={universeLabel} />
      </div>

      <div>
        <div className="text-[9px] tracking-wide text-slate-500 uppercase mb-1">Earlier patterns on {p.symbol}</div>
        {p.past && p.past.length > 0 ? (
          <ul className="space-y-1">{p.past.map((x, i) => <li key={i} className="text-[11px] text-slate-400">• {pastText(x)}</li>)}</ul>
        ) : (
          <p className="text-[11px] text-slate-500">No earlier confirmed pattern on this stock in the history scanned.</p>
        )}
      </div>

      {baseline && (
        <p className="text-[10px] leading-relaxed text-slate-500 border-t border-slate-800 pt-2">
          Reality check: this detector also finds a Fair-or-better shape in {Math.round(baseline.fair_plus * 100)}% of <em>random-walk</em> charts
          ({Math.round(baseline.strong_plus * 100)}% Strong-or-better, {Math.round(baseline.textbook * 100)}% Textbook). Treat a card as a chart worth looking at, not a signal.
        </p>
      )}
    </div>
  );
}

// Right-hand slide-over for the selected pattern (replaces the old squeezed third column, so the card
// grid keeps the full width). Click the backdrop, the X, or press Esc to close.
function PatternDrawer({ p, onClose, children }) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!p) { setShown(false); return undefined; }
    const raf = requestAnimationFrame(() => setShown(true));
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => { cancelAnimationFrame(raf); window.removeEventListener('keydown', onKey); };
  }, [p, onClose]);
  if (!p) return null;
  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Pattern detail">
      <div onClick={onClose} className={`absolute inset-0 bg-black/50 transition-opacity duration-200 ${shown ? 'opacity-100' : 'opacity-0'}`} />
      <div className={`absolute right-0 top-0 h-full w-full sm:w-[560px] max-w-full bg-slate-900 border-l border-slate-700 shadow-2xl flex flex-col transition-transform duration-200 ease-out ${shown ? 'translate-x-0' : 'translate-x-full'}`}>
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-800 shrink-0">
          <h3 className="text-base font-bold text-white">Pattern detail</h3>
          <button onClick={onClose} aria-label="Close" title="Close (Esc)" className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 text-lg leading-none">✕</button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  );
}

export default function ChartPatterns({ onOpenStock }) {
  const [universe, setUniverse] = useState(() => { try { return localStorage.getItem('fo-radar-pattern-universe') || 'nifty500'; } catch { return 'nifty500'; } });
  const [filters, setFilters] = useState({ family: null, direction: null, status: null, quality: null, within: null, volume: false, sort: 'composite', q: '' });
  const [data, setData] = useState(null);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [scanMsg, setScanMsg] = useState(null);
  const [analysis, setAnalysis] = useState(null);   // { sym, loading, error, data } -- single-stock, relaxed, on demand
  const reqId = useRef(0);
  const closeDrawer = useCallback(() => setSelected(null), []);

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
  useEffect(() => { setAnalysis(null); }, [filters.q, universe]);

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

  const analyze = (sym) => {
    setAnalysis({ sym, loading: true });
    fetch(`${API_BASE}/api/chart-patterns/symbol/${encodeURIComponent(sym)}/?universe=${universe}`)
      .then((r) => r.json().then((j) => ({ ok: r.ok, j })))
      .then(({ ok, j }) => setAnalysis(ok ? { sym, data: j } : { sym, error: j.error || 'Could not analyze this stock.' }))
      .catch((e) => setAnalysis({ sym, error: e.message }));
  };

  const loadMore = () => {
    setLoadingMore(true);
    fetch(buildUrl(items.length))
      .then((r) => r.json())
      .then((json) => setItems((prev) => [...prev, ...json.patterns.filter((p) => !prev.some((q) => q.id === p.id))]))
      .finally(() => setLoadingMore(false));
  };

  const scan = data?.scan || {};
  const universeLabel = (UNIVERSES.find((u) => u.key === universe) || {}).label || universe;
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

      <div className="grid gap-4 lg:grid-cols-[230px_minmax(0,1fr)]">
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
          {loading && <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-72 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />)}</div>}
          {error && <div className="text-center text-rose-400 text-sm py-8">⚠ {error}</div>}
          {!loading && !error && items.length === 0 && !filters.q.trim() && (
            <div className="text-center text-slate-500 text-sm py-12">
              {data?.all_patterns ? 'No patterns match these filters.' : scanState === 'running' ? 'Scanning — patterns appear here as they are found.' : 'Nothing here yet — press “Scan now” above.'}
            </div>
          )}
          {!loading && !error && items.length === 0 && filters.q.trim() && (() => {
            const sym = filters.q.trim().toUpperCase().replace(/[^A-Z0-9&-]/g, '');
            const filtered = filters.family || filters.direction || filters.status || filters.quality || filters.within || filters.volume;
            return (
              <div className="space-y-3">
                <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 space-y-2">
                  <div className="text-sm text-white font-semibold">No “{filters.q.trim()}” pattern in the {universeLabel} scan{filtered ? ' with these filters' : ''}.</div>
                  <p className="text-[11px] leading-relaxed text-slate-400">
                    {filtered ? 'Your filters may be hiding it — try Reset. Otherwise, the' : 'The'} stock was either scanned and nothing met the quality bar, is not in this universe, or the scan hasn’t reached it yet.
                    The scan only keeps Fair-or-better shapes; you can analyze this one stock now, including weaker candidates.
                  </p>
                  {sym && (
                    <button onClick={() => analyze(sym)} disabled={analysis?.loading}
                      className="text-[11px] px-3 py-1.5 rounded-lg border border-sky-500/50 bg-sky-500/10 text-sky-300 hover:bg-sky-500/20 disabled:opacity-50 flex items-center gap-1.5">
                      {analysis?.loading && <span className="inline-block w-2.5 h-2.5 rounded-full border border-sky-400 border-t-white animate-spin" />}
                      Analyze {sym} now
                    </button>
                  )}
                </div>
                {analysis?.error && <div className="text-[11px] text-amber-400">{analysis.error}</div>}
                {analysis?.data && (
                  <>
                    <div className="text-[11px] text-slate-400">{analysis.data.analysis.message} <span className="text-slate-600">({analysis.data.history_bars} daily candles fetched)</span></div>
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                      {analysis.data.patterns.map((p) => (
                        <div key={p.id} className="relative">
                          {p.below_bar && <span className="absolute -top-2 left-3 z-10 text-[9px] px-2 py-0.5 rounded-full border border-amber-500/50 bg-slate-900 text-amber-300">Below the quality bar</span>}
                          <PatternCard p={p} selected={selected?.id === p.id} onSelect={setSelected} />
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            );
          })()}
          {!loading && !error && items.length > 0 && (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
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
      </div>

      <PatternDrawer p={selected} onClose={closeDrawer}>
        <DetailPanel p={selected} embedded onOpenStock={onOpenStock} baseline={data?.baseline} rates={data?.base_rates} universeLabel={universeLabel} />
      </PatternDrawer>
    </div>
  );
}
