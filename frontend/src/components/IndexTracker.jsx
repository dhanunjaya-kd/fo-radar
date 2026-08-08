import { useEffect, useState } from 'react';

// Relative on purpose -- see the same note in SignalList.jsx. Routes
// through Vite's dev-server proxy so this works from any host the page
// was loaded from (localhost, home wifi, Tailscale) with no changes.
const API_BASE = import.meta.env.VITE_API_URL || '';

const BIAS_STYLE = {
  'Bullish (Strong)': 'text-emerald-400 bg-emerald-500/15',
  'Bullish': 'text-emerald-400 bg-emerald-500/10',
  'Neutral': 'text-amber-400 bg-amber-500/10',
  'Bearish': 'text-rose-400 bg-rose-500/10',
  'Bearish (Strong)': 'text-rose-400 bg-rose-500/15',
};

function fmt(n) {
  if (n == null || isNaN(n)) return '—';
  return Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 });
}
function fmtOi(n) {
  if (n == null || isNaN(n)) return '—';
  return `${(n / 100000).toFixed(1)}L`;
}
function fmtChg(n) {
  if (n == null || isNaN(n)) return '—';
  const sign = n >= 0 ? '+' : '';
  return `${sign}${(n / 100000).toFixed(1)}L`;
}
function fmtPct(n, digits = 2) {
  if (n == null || isNaN(n)) return '—';
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`;
}

// --- Grouped headline: Price / Open Interest / Sentiment, side by side ---
// Leads with the latest snapshot in three clearly separated cards instead
// of one flat 17-column table row -- each card answers one question
// (what's price doing / where's OI positioned / what's the read) rather
// than making you scan across the whole width to piece it together.
function LatestSnapshot({ indexName, row }) {
  if (!row) return null;
  const isUp = (row['Change %'] || 0) >= 0;
  const confirms = row['Price Confirms Bias'];

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
      {/* Price */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
        <p className="text-[11px] text-slate-500 uppercase tracking-wide flex items-center gap-1.5 mb-2">
          📈 Price
        </p>
        <p className="text-2xl font-bold text-white leading-none mb-1">{fmt(row.Spot)}</p>
        <p className={`text-sm font-medium mb-3 ${isUp ? 'text-emerald-400' : 'text-rose-400'}`}>
          {fmtPct(row['Change %'])}
        </p>
        <div className="space-y-1 text-xs pt-3 border-t border-slate-800/60">
          <div className="flex justify-between"><span className="text-slate-500">Futures</span><span className="text-indigo-300">{fmt(row.Fut)}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">India VIX</span><span className="text-orange-400">{row.VIX != null ? row.VIX.toFixed(2) : '—'}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">IV (ATM)</span><span className="text-amber-400">{row['IV %'] != null ? `${row['IV %'].toFixed(1)}%` : '—'}</span></div>
        </div>
      </div>

      {/* Open Interest */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
        <p className="text-[11px] text-slate-500 uppercase tracking-wide flex items-center gap-1.5 mb-2">
          📊 Open interest
        </p>
        <p className="text-2xl font-bold text-white leading-none mb-1">{row.PCR != null ? row.PCR.toFixed(2) : '—'}</p>
        <p className="text-sm text-slate-400 mb-3">PCR · Max pain {fmt(row['Max Pain'])}</p>
        <div className="space-y-1 text-xs pt-3 border-t border-slate-800/60">
          <div className="flex justify-between">
            <span className="text-slate-500">Put wall</span>
            <span className="text-emerald-400">{fmt(row['Highest Put OI Strike'])} <span className="text-slate-500">({fmtOi(row['Highest Put OI Value'])})</span></span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Call wall</span>
            <span className="text-rose-400">{fmt(row['Highest Call OI Strike'])} <span className="text-slate-500">({fmtOi(row['Highest Call OI Value'])})</span></span>
          </div>
          <div className="flex justify-between"><span className="text-slate-500">Total put / call OI</span><span className="text-slate-300">{fmtOi(row['Total Put OI'])} / {fmtOi(row['Total Call OI'])}</span></div>
        </div>
      </div>

      {/* Sentiment / Bias */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
        <p className="text-[11px] text-slate-500 uppercase tracking-wide flex items-center gap-1.5 mb-2">
          🧭 Bias
        </p>
        <span className={`inline-block text-sm font-semibold px-3 py-1 rounded-full mb-3 ${BIAS_STYLE[row.Bias] || 'text-slate-400 bg-slate-700/30'}`}>
          {row.Bias || '—'}
        </span>
        <div className="space-y-1 text-xs pt-3 border-t border-slate-800/60">
          <div className="flex justify-between">
            <span className="text-slate-500">Price confirms?</span>
            <span className={confirms === '✓ Confirmed' ? 'text-emerald-400' : confirms === '⚠ Conflict' ? 'text-rose-400' : 'text-slate-500'}>
              {confirms || '—'}
            </span>
          </div>
          <div className="flex justify-between"><span className="text-slate-500">Support / resistance</span><span className="text-slate-300">{fmt(row.Support)} / {fmt(row.Resistance)}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">ATM strike</span><span className="text-slate-300">{fmt(row['ATM Strike'])}</span></div>
        </div>
      </div>
    </div>
  );
}

// --- Compact history table: same three groupings, visually separated with
// column-group backgrounds instead of a flat wall of columns, for the
// scroll-back/backtest view under the headline. ---
function HistoryTable({ rows }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-slate-500 uppercase text-[9px]">
            <th className="text-left px-2 py-1.5 font-medium">Time</th>
            <th className="text-right px-2 py-1.5 font-medium bg-slate-800/30">Spot</th>
            <th className="text-right px-2 py-1.5 font-medium bg-slate-800/30">Chg%</th>
            <th className="text-right px-2 py-1.5 font-medium bg-indigo-500/5">PCR</th>
            <th className="text-right px-2 py-1.5 font-medium bg-indigo-500/5">Put OI</th>
            <th className="text-right px-2 py-1.5 font-medium bg-indigo-500/5">Call OI</th>
            <th className="text-right px-2 py-1.5 font-medium bg-indigo-500/5">Max pain</th>
            <th className="text-center px-2 py-1.5 font-medium">Bias</th>
            <th className="text-center px-2 py-1.5 font-medium">Confirms?</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-slate-800/40 hover:bg-slate-800/20">
              <td className="px-2 py-1.5 text-slate-500 font-mono">{r.Time}</td>
              <td className="px-2 py-1.5 text-right text-white bg-slate-800/20">{fmt(r.Spot)}</td>
              <td className={`px-2 py-1.5 text-right bg-slate-800/20 ${(r['Change %'] || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {fmtPct(r['Change %'])}
              </td>
              <td className="px-2 py-1.5 text-right text-indigo-400 bg-indigo-500/5">{r.PCR != null ? r.PCR.toFixed(2) : '—'}</td>
              <td className="px-2 py-1.5 text-right text-emerald-400 bg-indigo-500/5">{fmtOi(r['Put OI (ATM)'])}</td>
              <td className="px-2 py-1.5 text-right text-rose-400 bg-indigo-500/5">{fmtOi(r['Call OI (ATM)'])}</td>
              <td className="px-2 py-1.5 text-right text-slate-300 bg-indigo-500/5">{fmt(r['Max Pain'])}</td>
              <td className="px-2 py-1.5 text-center">
                <span className={`px-1.5 py-0.5 rounded-full text-[9px] font-semibold ${BIAS_STYLE[r.Bias] || 'text-slate-400 bg-slate-700/30'}`}>
                  {r.Bias}
                </span>
              </td>
              <td className="px-2 py-1.5 text-center">
                <span className={
                  r['Price Confirms Bias'] === '✓ Confirmed' ? 'text-emerald-400' :
                  r['Price Confirms Bias'] === '⚠ Conflict' ? 'text-rose-400' : 'text-slate-600'
                }>
                  {r['Price Confirms Bias'] === '✓ Confirmed' ? '✓' : r['Price Confirms Bias'] === '⚠ Conflict' ? '⚠' : '—'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Day-wise Bias-accuracy backtest -- does the Bias reading (Bullish/
// Bearish) actually predict where price goes next, broken out by day.
// Loaded lazily (only once the section is first expanded) since it's a
// real computation over every historical snapshot file, not a cheap
// cache read like the rest of this tab. Shows the 30-minute horizon
// inline for a quick read; the download has 15/30/60min side by side.
function BacktestSection({ indexName }) {
  const [show, setShow] = useState(false);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!show || data || loading) return;
    setLoading(true);
    fetch(`${API_BASE}/api/index-backtest/${indexName}/`)
      .then(r => r.json())
      .then(d => { setData(d); setError(null); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [show, indexName, data, loading]);

  const days = data ? Object.keys(data.horizons?.[30] || {}) : [];
  const rows = [];
  if (data) {
    for (const day of days) {
      for (const [bias, r] of Object.entries(data.horizons[30][day])) {
        if (r.total > 0) rows.push({ day, bias, ...r });
      }
    }
  }

  return (
    <div className="mt-3 border-t border-slate-800/60 pt-3">
      <div className="flex items-center justify-between mb-2 gap-2">
        <button
          onClick={() => setShow(v => !v)}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
        >
          {show ? '▲ Hide' : '▼ Show'} Bias backtest (does it predict price?)
        </button>
        <a
          href={`${API_BASE}/api/index-backtest/${indexName}/export/`}
          className="text-[11px] font-medium text-indigo-400 bg-indigo-500/10 border border-indigo-500/25 px-2.5 py-1 rounded-lg hover:bg-indigo-500/20 transition-colors shrink-0"
          download
        >
          📥 Export
        </a>
      </div>

      {show && (
        <>
          {loading && <div className="py-4 text-center text-slate-500 text-xs">Crunching the numbers...</div>}
          {error && <div className="py-2 text-center text-rose-400 text-xs">⚠ {error}</div>}
          {data && rows.length === 0 && (
            <div className="py-4 text-center text-slate-500 text-xs">
              Not enough history yet — needs a directional Bias reading followed by a later snapshot to test against. More days logged = more here.
            </div>
          )}
          {rows.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-slate-800">
              <p className="text-[10px] text-slate-500 px-3 pt-2">30-minute look-ahead shown here — the download has 15/30/60min side by side.</p>
              <table className="w-full text-xs mt-1">
                <thead>
                  <tr className="bg-slate-800/60 text-slate-500 text-[10px] uppercase">
                    <th className="text-left px-3 py-2">Date</th>
                    <th className="text-left px-3 py-2">Bias</th>
                    <th className="text-right px-3 py-2">Hit %</th>
                    <th className="text-right px-3 py-2">Samples</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(r => (
                    <tr key={`${r.day}-${r.bias}`} className="border-t border-slate-800/60">
                      <td className="px-3 py-1.5 text-slate-300 whitespace-nowrap">{r.day}</td>
                      <td className="px-3 py-1.5">
                        <span className={`px-1.5 py-0.5 rounded-full text-[10px] whitespace-nowrap ${BIAS_STYLE[r.bias] || 'text-slate-400'}`}>{r.bias}</span>
                      </td>
                      <td className={`px-3 py-1.5 text-right font-semibold ${r.hit_rate >= 50 ? 'text-emerald-400' : 'text-rose-400'}`}>{r.hit_rate}%</td>
                      <td className="px-3 py-1.5 text-right text-slate-500">{r.total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function IndexSection({ indexName }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch(`${API_BASE}/api/index-tracker/${indexName}/`)
        .then(r => r.json())
        .then(data => {
          if (cancelled) return;
          setRows(data.snapshots || []);
          setError(null);
        })
        .catch(e => { if (!cancelled) setError(e.message); })
        .finally(() => { if (!cancelled) setLoading(false); });
    };
    load();
    const interval = setInterval(load, 60000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [indexName]);

  return (
    <div className="bg-slate-900/50 rounded-xl border border-slate-800 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h3 className="text-sm font-bold text-white">{indexName}</h3>
        <a
          href={`${API_BASE}/api/index-tracker/${indexName}/export/`}
          className="text-[11px] font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/25 px-2.5 py-1 rounded-lg hover:bg-emerald-500/20 transition-colors"
          download
        >
          📥 Export
        </a>
      </div>

      <div className="p-4">
        {loading && rows.length === 0 && (
          <div className="py-8 text-center text-slate-500 text-sm">Loading {indexName} snapshots...</div>
        )}
        {!loading && rows.length === 0 && !error && (
          <div className="py-8 text-center text-slate-500 text-sm">
            No snapshots logged yet today. A new one is taken every scan cycle once Fyers is live.
          </div>
        )}
        {error && <div className="py-4 text-center text-rose-400 text-sm">⚠ {error}</div>}

        {rows.length > 0 && (
          <>
            <LatestSnapshot indexName={indexName} row={rows[0]} />
            <button
              onClick={() => setShowHistory(v => !v)}
              className="w-full flex items-center justify-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 py-2 border-t border-slate-800/60 transition-colors"
            >
              {showHistory ? '▲ Hide' : '▼ Show'} full history ({rows.length} snapshots today)
            </button>
            {showHistory && (
              <div className="mt-3">
                <HistoryTable rows={rows} />
              </div>
            )}
            <BacktestSection indexName={indexName} />
          </>
        )}
      </div>
    </div>
  );
}

export default function IndexTracker() {
  return (
    <div className="space-y-4">
      <div className="bg-indigo-500/10 border border-indigo-500/20 rounded-lg px-4 py-2.5 text-xs text-indigo-300">
        NIFTY and BANKNIFTY only, snapshotted every scan cycle. "Fut" is the real front-month futures
        price. "Fut OI Chg" (futures open interest specifically) still isn't tracked — that data wasn't
        exposed in the same quote that gives the futures price — left out rather than faked.
      </div>
      <IndexSection indexName="NIFTY" />
      <IndexSection indexName="BANKNIFTY" />
    </div>
  );
}
