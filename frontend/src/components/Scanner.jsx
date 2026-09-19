import { useState, useEffect, useRef } from 'react';
import ChartModal from './ChartModal';

const API_BASE = import.meta.env.VITE_API_URL || '';

const UNIVERSES = [
  { key: 'all', label: 'All Stocks', icon: '🌐' },
  { key: 'nifty50', label: 'Nifty 50', icon: '🏆' },
  { key: 'nifty100', label: 'Nifty 100', icon: '💎' },
  { key: 'nifty200', label: 'Nifty 200', icon: '📊' },
  { key: 'nifty500', label: 'Nifty 500', icon: '📋' },
  { key: 'fno', label: 'F&O Stocks', icon: '⚡' },
];

function fmtPrice(p) {
  if (p === null || p === undefined) return '—';
  return `₹${p.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}
function fmtPct(p) {
  if (p === null || p === undefined) return '—';
  const sign = p >= 0 ? '+' : '';
  return `${sign}${p.toFixed(2)}%`;
}
function fmtVol(v) {
  if (!v) return '—';
  if (v >= 1e7) return `${(v / 1e7).toFixed(1)}Cr`;
  if (v >= 1e5) return `${(v / 1e5).toFixed(1)}L`;
  return v.toLocaleString('en-IN');
}

// Same shape as IndexCard.jsx's own Sparkline -- kept intentionally
// simple here (no hover tooltip) since a scanner grid can show
// dozens of these at once; a per-card hover state for every card
// isn't worth the render cost for what's meant to be a quick visual
// trend, not a precise reading (that's what clicking through to the
// stock is for).
function MiniSparkline({ values, positive }) {
  if (!values || values.length < 2) return <div className="h-10" />;
  const w = 120, h = 40, pad = 2;
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const points = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (w - pad * 2);
    const y = pad + (1 - (v - min) / range) * (h - pad * 2);
    return `${x},${y}`;
  });
  const color = positive ? '#34d399' : '#ef4444';
  const fillPoints = `${pad},${h} ${points.join(' ')} ${w - pad},${h}`;
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <polygon points={fillPoints} fill={color} opacity="0.12" />
      <polyline points={points.join(' ')} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

function gradeColor(grade) {
  if (!grade) return 'text-slate-500 border-slate-700';
  if (grade === 'A+' || grade === 'A') return 'text-emerald-400 border-emerald-500/40';
  if (grade === 'B') return 'text-sky-400 border-sky-500/40';
  if (grade === 'C') return 'text-amber-400 border-amber-500/40';
  return 'text-rose-400 border-rose-500/40';
}

// Sep 19 2026: colored by what each pattern actually signals, not a
// generic palette -- bullish reversal/continuation shapes green,
// bearish ones rose, genuinely indecisive ones (a plain Doji, Spinning
// Top, Long-Legged Doji) amber, matching how a trader would actually
// read them rather than an arbitrary color rotation.
const BULLISH_PATTERNS = new Set(['Hammer', 'Inverted Hammer', 'Bullish Engulfing', 'Morning Star', 'Dragonfly Doji', 'Bull Marubozu']);
const BEARISH_PATTERNS = new Set(['Hanging Man', 'Shooting Star', 'Bearish Engulfing', 'Dark Cloud Cover', 'Gravestone Doji', 'Bear Marubozu']);
function patternStyle(pattern) {
  if (BULLISH_PATTERNS.has(pattern)) return 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10';
  if (BEARISH_PATTERNS.has(pattern)) return 'text-rose-400 border-rose-500/40 bg-rose-500/10';
  return 'text-amber-400 border-amber-500/40 bg-amber-500/10';
}

function fmt52w(high) {
  if (high === null || high === undefined) return '—';
  return `₹${high.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}

// Sep 19 2026: ✓/✗/• checklist + trigger/stop/target, built entirely
// from stock.explain -- every line is a real number the backend
// already computed (see _generate_explain's own docstring: same ATR
// stop/target formula the live signal engine uses for real trades,
// not a separate model). This component only renders what it's given;
// no client-side guessing.
function ExplainPanel({ explain }) {
  if (!explain) return null;
  return (
    <div className="mt-2 pt-2 border-t border-slate-800 space-y-2">
      <div className="space-y-1">
        {explain.checks.map((c, i) => (
          <div key={i} className="flex items-start gap-1.5 text-[11px]">
            <span className={c.ok === true ? 'text-emerald-400' : c.ok === false ? 'text-rose-400' : 'text-slate-500'}>
              {c.ok === true ? '✓' : c.ok === false ? '✗' : '·'}
            </span>
            <span className="text-slate-300">{c.text}</span>
          </div>
        ))}
      </div>
      {(explain.trigger != null || explain.stop != null || explain.target != null) && (
        <div className="grid grid-cols-3 gap-2 text-center text-[10px] pt-1">
          <div className="rounded-lg bg-slate-800/60 py-1.5">
            <div className="text-slate-500 uppercase">Trigger</div>
            <div className="text-white font-semibold">{explain.trigger != null ? `₹${explain.trigger}` : '—'}</div>
            <div className="text-slate-600">{explain.trigger_label}</div>
          </div>
          <div className="rounded-lg bg-slate-800/60 py-1.5">
            <div className="text-slate-500 uppercase">Stop</div>
            <div className="text-rose-400 font-semibold">{explain.stop != null ? `₹${explain.stop}` : '—'}</div>
            <div className="text-slate-600">{explain.risk_pct != null ? `${explain.risk_pct}% risk` : ''}</div>
          </div>
          <div className="rounded-lg bg-slate-800/60 py-1.5">
            <div className="text-slate-500 uppercase">2R Target</div>
            <div className="text-emerald-400 font-semibold">{explain.target != null ? `₹${explain.target}` : '—'}</div>
            <div className="text-slate-600">from this close</div>
          </div>
        </div>
      )}
    </div>
  );
}

function StockCard({ stock, onOpenChart }) {
  const positive = (stock.change_percent || 0) >= 0;
  const [showExplain, setShowExplain] = useState(false);
  return (
    <div
      onClick={() => onOpenChart(stock.symbol)}
      className="group relative rounded-xl bg-gradient-to-b from-slate-900/80 to-slate-900/40 border border-slate-800 p-4 hover:border-slate-600 hover:shadow-lg hover:shadow-black/20 transition-all duration-200 cursor-pointer"
    >
      <div className="flex items-start justify-between mb-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-white truncate">{stock.symbol}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700 shrink-0">NSE</span>
          </div>
          <div className="text-[10px] text-slate-500 mt-0.5 truncate">{stock.company_name || stock.sector}</div>
        </div>
        {stock.score != null && (
          <div className={`flex items-center gap-1 rounded-full border px-2 py-1 shrink-0 ${gradeColor(stock.grade)}`}>
            <span className="text-xs font-bold">{stock.score}</span>
            <span className="text-[10px] opacity-70">{stock.grade}</span>
          </div>
        )}
      </div>

      <div className="text-xl font-bold text-white">{fmtPrice(stock.price)}</div>
      <div className={`text-xs font-medium ${positive ? 'text-emerald-400' : 'text-rose-400'}`}>
        {positive ? '↗' : '↘'} {fmtPct(stock.change_percent)}
      </div>

      {/* Sep 19 2026: whole card opens the chart now, not just this
          area -- was click-anywhere-on-the-sparkline only, apparently
          not discoverable/reliable enough. ChartModal already exists
          (Watchlist.jsx/TopLiveSignals.jsx both use it against the
          same real /api/candles/ endpoint), same trigger pattern
          those two already use. The hover label here is now purely a
          visual cue, not a separate click target. */}
      <div className="relative my-2">
        <MiniSparkline values={stock.sparkline} positive={positive} />
        {stock.sparkline && (
          <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-slate-950/40 rounded-lg pointer-events-none">
            <span className="text-[11px] font-medium text-slate-200 bg-slate-800/90 border border-slate-600 rounded-full px-3 py-1">View Chart</span>
          </div>
        )}
      </div>

      <div className="grid grid-cols-4 gap-2 text-center text-[10px] pt-2 border-t border-slate-800">
        <div>
          <div className="text-slate-500">VOL</div>
          <div className="text-slate-300 font-medium">{fmtVol(stock.volume)}</div>
        </div>
        <div>
          <div className="text-slate-500">RSI</div>
          <div className="text-slate-300 font-medium">{stock.rsi != null ? stock.rsi.toFixed(0) : '—'}</div>
        </div>
        <div>
          <div className="text-slate-500">MACD</div>
          <div className={`font-medium ${stock.macd_bias === 'Bull' ? 'text-emerald-400' : stock.macd_bias === 'Bear' ? 'text-rose-400' : 'text-slate-300'}`}>
            {stock.macd_bias || '—'}
          </div>
        </div>
        <div>
          <div className="text-slate-500">52W HI</div>
          <div className="text-slate-300 font-medium">{fmt52w(stock.high_52w)}</div>
        </div>
      </div>

      {stock.patterns && stock.patterns.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-2 mt-2 border-t border-slate-800">
          {stock.patterns.map(p => (
            <span key={p} className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border ${patternStyle(p)}`}>
              <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />
              {p}
            </span>
          ))}
        </div>
      )}

      {stock.explain && (
        <>
          <button
            onClick={(e) => { e.stopPropagation(); setShowExplain(v => !v); }}
            className="mt-2 text-[10px] text-slate-500 hover:text-slate-300 transition-colors flex items-center gap-1"
          >
            {showExplain ? 'Hide analysis' : 'Show analysis'}
            <span className={`transition-transform ${showExplain ? 'rotate-180' : ''}`}>▾</span>
          </button>
          {showExplain && <div onClick={(e) => e.stopPropagation()}><ExplainPanel explain={stock.explain} /></div>}
        </>
      )}
    </div>
  );
}

export default function Scanner() {
  const [universe, setUniverse] = useState('nifty500');
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [selectedPattern, setSelectedPattern] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [chartSymbol, setChartSymbol] = useState(null);
  const dropdownRef = useRef(null);

  // Sep 19 2026: was a single fetch, full skeleton on every load --
  // fine once the backend's own cache is warm, but on a cold cache
  // (evenings/weekends, before the off-hours warmup has had time to
  // run) the first response can legitimately come back with most of
  // the universe still uncovered. Silently expecting the user to hit
  // refresh themselves read as "broken," not "still loading." Now:
  // first load shows the real skeleton; if the response comes back
  // incomplete, it keeps whatever loaded so far ON SCREEN and quietly
  // retries in the background (no skeleton flash) until covered
  // catches up to universe_size or 6 retries are used -- roughly two
  // minutes of ceiling, long enough for a cold cache's early batches
  // to land without polling forever if something's genuinely stuck
  // (not authenticated, say).
  useEffect(() => {
    let cancelled = false;
    let retries = 0;
    const MAX_RETRIES = 6;
    setSelectedPattern(null);  // patterns differ per universe -- a filter picked for one shouldn't silently carry into another
    setSearchQuery('');

    const load = (isRetry) => {
      if (isRetry) setRefreshing(true); else { setLoading(true); setError(null); }
      fetch(`${API_BASE}/api/scanner/?universe=${universe}`)
        .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(json => {
          if (cancelled) return;
          setData(json);
          setLoading(false);
          setRefreshing(false);
          if (json.covered < json.universe_size && retries < MAX_RETRIES) {
            retries += 1;
            setTimeout(() => { if (!cancelled) load(true); }, 4000);
          }
        })
        .catch(e => {
          if (cancelled) return;
          setError(e.message);
          setLoading(false);
          setRefreshing(false);
        });
    };
    load(false);
    return () => { cancelled = true; };
  }, [universe]);

  useEffect(() => {
    const onClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) setDropdownOpen(false);
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  const current = UNIVERSES.find(u => u.key === universe);

  // Sep 19 2026: pattern filter chips -- counts computed from the
  // stocks already loaded in this response (every card's own
  // stock.patterns array, same data the tags on each card already
  // show), not a second backend call. Clicking a chip filters the
  // grid client-side; clicking the same chip again clears it.
  const patternCounts = {};
  (data?.stocks || []).forEach(s => (s.patterns || []).forEach(p => {
    patternCounts[p] = (patternCounts[p] || 0) + 1;
  }));
  const sortedPatterns = Object.entries(patternCounts).sort((a, b) => b[1] - a[1]);
  const visibleStocks = data
    ? data.stocks
        .filter(s => !selectedPattern || (s.patterns || []).includes(selectedPattern))
        .filter(s => {
          if (!searchQuery.trim()) return true;
          const q = searchQuery.trim().toLowerCase();
          return s.symbol.toLowerCase().includes(q) || (s.company_name || '').toLowerCase().includes(q);
        })
    : [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h2 className="text-lg font-bold text-white">Scanner</h2>
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen(o => !o)}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-sm text-white hover:border-slate-500 transition-colors"
          >
            <span>{current?.icon}</span>
            <span>{current?.label}</span>
            <span className="text-slate-500 text-xs">▾</span>
          </button>
          {dropdownOpen && (
            <div className="absolute right-0 mt-1 w-48 rounded-lg bg-slate-900 border border-slate-700 shadow-xl z-30 overflow-hidden">
              {UNIVERSES.map(u => (
                <button
                  key={u.key}
                  onClick={() => { setUniverse(u.key); setDropdownOpen(false); }}
                  className={`w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-slate-800 transition-colors ${u.key === universe ? 'text-emerald-400' : 'text-slate-300'}`}
                >
                  {u.key === universe && <span>✓</span>}
                  <span>{u.icon}</span>
                  <span>{u.label}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-sm">🔍</span>
        <input
          type="text"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          placeholder="Search symbols, company names…"
          className="w-full pl-9 pr-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-slate-500 transition-colors"
        />
      </div>

      {loading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-48 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />
          ))}
        </div>
      )}
      {error && (
        <div className="text-center text-rose-400 text-sm py-8">⚠ {error}</div>
      )}
      {!loading && !error && data && (
        <>
          <div className="text-xs text-slate-500">
            {data.covered} of {data.universe_size} stocks have live data right now
            {refreshing && <span className="text-sky-400"> — fetching more in the background…</span>}
            {!refreshing && data.covered < data.universe_size && (
              <span className="text-amber-400">
                {' '}— {universe === 'all'
                  ? "the rest aren't covered by this app's local data at all."
                  : "the rest didn't have a cached quote yet — this fills in over the next couple of minutes on a cold cache (first load of the day), no need to keep refreshing manually."}
              </span>
            )}
          </div>

          {sortedPatterns.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] text-slate-500 flex items-center gap-1">⏚ PATTERNS</span>
              {sortedPatterns.map(([p, count]) => (
                <button
                  key={p}
                  onClick={() => setSelectedPattern(sp => (sp === p ? null : p))}
                  className={`text-[11px] px-2.5 py-1 rounded-full border transition-colors ${
                    selectedPattern === p
                      ? 'bg-emerald-500/20 border-emerald-500/60 text-emerald-300'
                      : 'bg-slate-900/60 border-slate-700 text-slate-300 hover:border-slate-500'
                  }`}
                >
                  {p} <span className="opacity-60">{count}</span>
                </button>
              ))}
              {selectedPattern && (
                <button onClick={() => setSelectedPattern(null)} className="text-[11px] text-slate-500 hover:text-slate-300 underline">
                  Clear
                </button>
              )}
            </div>
          )}

          {visibleStocks.length === 0 ? (
            <div className="text-center text-slate-500 text-sm py-12">
              {searchQuery.trim()
                ? `No match for "${searchQuery}" in this universe${selectedPattern ? ` with the "${selectedPattern}" tag` : ''}.`
                : selectedPattern
                  ? `No stocks currently tagged "${selectedPattern}" in this universe.`
                  : "No data yet for this universe — give it a few seconds and refresh; this fetches on demand, it doesn't need the market to be open."}
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {visibleStocks.map(s => <StockCard key={s.symbol} stock={s} onOpenChart={setChartSymbol} />)}
            </div>
          )}
        </>
      )}

      {chartSymbol && <ChartModal symbol={chartSymbol} onClose={() => setChartSymbol(null)} />}
    </div>
  );
}
