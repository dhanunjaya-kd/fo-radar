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

// One dense table instead of 3 separate cards plus a differently-
// formatted history table below them -- easier to scan across a row
// than to jump between visually separated boxes to piece together the
// same picture. Latest snapshot is always the first (highlighted) row;
// older snapshots from today are additional rows, shown via the same
// toggle that used to gate a separate history section.
function SnapshotTable({ rows, showAll, onToggleShowAll }) {
  const visible = showAll ? rows : rows.slice(0, 1);

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-slate-800/60 text-slate-500 text-[10px] uppercase">
            <th className="text-left px-2.5 py-2 font-medium">Time</th>
            <th className="text-right px-2.5 py-2 font-medium">Spot</th>
            <th className="text-right px-2.5 py-2 font-medium">Chg%</th>
            <th className="text-center px-2.5 py-2 font-medium">CAS</th>
            <th className="text-right px-2.5 py-2 font-medium">Futures</th>
            <th className="text-right px-2.5 py-2 font-medium">Fut OI</th>
            <th className="text-right px-2.5 py-2 font-medium">Fut OI Chg%</th>
            <th className="text-right px-2.5 py-2 font-medium">VIX</th>
            <th className="text-right px-2.5 py-2 font-medium">IV%</th>
            <th className="text-right px-2.5 py-2 font-medium">PCR</th>
            <th className="text-right px-2.5 py-2 font-medium">Max Pain</th>
            <th className="text-right px-2.5 py-2 font-medium">Put Wall</th>
            <th className="text-right px-2.5 py-2 font-medium">Call Wall</th>
            <th className="text-right px-2.5 py-2 font-medium">Put OI</th>
            <th className="text-right px-2.5 py-2 font-medium">Call OI</th>
            <th className="text-center px-2.5 py-2 font-medium">Bias</th>
            <th className="text-center px-2.5 py-2 font-medium">Confirms?</th>
            <th className="text-right px-2.5 py-2 font-medium">Support</th>
            <th className="text-right px-2.5 py-2 font-medium">Resistance</th>
            <th className="text-right px-2.5 py-2 font-medium">ATM Strike</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((r, i) => {
            const isUp = (r['Change %'] || 0) >= 0;
            const confirms = r['Price Confirms Bias'];
            return (
              <tr key={i} className={`border-t border-slate-800/40 ${i === 0 ? 'bg-slate-800/30' : 'hover:bg-slate-800/20'}`}>
                <td className="px-2.5 py-2 text-slate-500 font-mono whitespace-nowrap">{r.Time}</td>
                <td className="px-2.5 py-2 text-right text-white font-semibold whitespace-nowrap">{fmt(r.Spot)}</td>
                <td className={`px-2.5 py-2 text-right whitespace-nowrap ${isUp ? 'text-emerald-400' : 'text-rose-400'}`}>{fmtPct(r['Change %'])}</td>
                <td className="px-2.5 py-2 text-center">
                  {r['CAS Auction'] ? (
                    <span
                      className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/25 whitespace-nowrap"
                      title="Taken during the 3:15-3:35 PM Closing Auction Session -- Chg% and Confirms? here reflect the real auction mechanism, not necessarily a normal intraday move"
                    >
                      Auction
                    </span>
                  ) : (
                    <span className="text-slate-600">—</span>
                  )}
                </td>
                <td className="px-2.5 py-2 text-right text-indigo-300 whitespace-nowrap">{fmt(r.Fut)}</td>
                <td className="px-2.5 py-2 text-right text-indigo-300 whitespace-nowrap">{fmtOi(r['Fut OI'])}</td>
                <td className={`px-2.5 py-2 text-right whitespace-nowrap ${(r['Fut OI Chg %'] || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{fmtPct(r['Fut OI Chg %'])}</td>
                <td className="px-2.5 py-2 text-right text-orange-400 whitespace-nowrap">{r.VIX != null ? r.VIX.toFixed(2) : '—'}</td>
                <td className="px-2.5 py-2 text-right text-amber-400 whitespace-nowrap">{r['IV %'] != null ? `${r['IV %'].toFixed(1)}%` : '—'}</td>
                <td className="px-2.5 py-2 text-right text-indigo-400 whitespace-nowrap">{r.PCR != null ? r.PCR.toFixed(2) : '—'}</td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap">{fmt(r['Max Pain'])}</td>
                <td className="px-2.5 py-2 text-right text-emerald-400 whitespace-nowrap">{fmt(r['Highest Put OI Strike'])}</td>
                <td className="px-2.5 py-2 text-right text-rose-400 whitespace-nowrap">{fmt(r['Highest Call OI Strike'])}</td>
                <td className="px-2.5 py-2 text-right text-emerald-400 whitespace-nowrap">{fmtOi(r['Total Put OI'])}</td>
                <td className="px-2.5 py-2 text-right text-rose-400 whitespace-nowrap">{fmtOi(r['Total Call OI'])}</td>
                <td className="px-2.5 py-2 text-center">
                  <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-semibold whitespace-nowrap ${BIAS_STYLE[r.Bias] || 'text-slate-400 bg-slate-700/30'}`}>
                    {r.Bias || '—'}
                  </span>
                </td>
                <td className="px-2.5 py-2 text-center">
                  <span className={confirms === '✓ Confirmed' ? 'text-emerald-400' : confirms === '⚠ Conflict' ? 'text-rose-400' : 'text-slate-600'}>
                    {confirms === '✓ Confirmed' ? '✓' : confirms === '⚠ Conflict' ? '⚠' : '—'}
                  </span>
                </td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap">{fmt(r.Support)}</td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap">{fmt(r.Resistance)}</td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap">{fmt(r['ATM Strike'])}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {rows.length > 1 && (
        <button
          onClick={onToggleShowAll}
          className="w-full flex items-center justify-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 py-2 border-t border-slate-800/60 transition-colors"
        >
          {showAll ? '▲ Hide older snapshots' : `▼ Show ${rows.length - 1} more snapshot${rows.length - 1 === 1 ? '' : 's'} today`}
        </button>
      )}
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

const DISPLAY_NAME = {
  NIFTY: 'NIFTY',
  BANKNIFTY: 'BANKNIFTY',
  CRUDEOIL: 'CRUDE OIL',
  CRUDEOILM: 'CRUDE OIL MINI',
};

// Day-by-day price move specifically attributable to the CAS auction
// window -- last reading before 3:15 PM vs first reading after 3:35 PM,
// isolating the auction's own effect from ordinary intraday movement.
// Same collapsible pattern as BacktestSection above.
function CASMovesSection({ indexName }) {
  const [show, setShow] = useState(false);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!show || data || loading) return;
    setLoading(true);
    fetch(`${API_BASE}/api/cas-auction-moves/${indexName}/`)
      .then(r => r.json())
      .then(d => { setData(d); setError(null); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [show, indexName, data, loading]);

  const moves = data?.moves || [];

  return (
    <div className="mt-3 border-t border-slate-800/60 pt-3">
      <button
        onClick={() => setShow(v => !v)}
        className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors mb-2"
      >
        {show ? '▲ Hide' : '▼ Show'} CAS auction moves (day-by-day)
      </button>

      {show && (
        <>
          {loading && <div className="py-4 text-center text-slate-500 text-xs">Loading...</div>}
          {error && <div className="py-2 text-center text-rose-400 text-xs">⚠ {error}</div>}
          {data && moves.length === 0 && (
            <div className="py-4 text-center text-slate-500 text-xs max-w-md">
              No complete days yet — needs a snapshot both before 3:15 PM and after 3:35 PM on the same day. Days before Aug 13, 2026 won't qualify (the scanner used to stop at 3:30 PM, before the auction resolved) — real data only accumulates from today forward.
            </div>
          )}
          {moves.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-slate-800">
              <p className="text-[10px] text-slate-500 px-3 pt-2">Last reading before 3:15 PM vs first reading after 3:35 PM — isolates the auction's own effect from normal intraday movement.</p>
              <table className="w-full text-xs mt-1">
                <thead>
                  <tr className="bg-slate-800/60 text-slate-500 text-[10px] uppercase">
                    <th className="text-left px-3 py-2">Date</th>
                    <th className="text-right px-3 py-2">Pre-Auction</th>
                    <th className="text-right px-3 py-2">Post-Auction</th>
                    <th className="text-right px-3 py-2">Move</th>
                  </tr>
                </thead>
                <tbody>
                  {moves.map(m => (
                    <tr key={m.date} className="border-t border-slate-800/60">
                      <td className="px-3 py-1.5 text-slate-300 whitespace-nowrap">{m.date}</td>
                      <td className="px-3 py-1.5 text-right text-slate-300 whitespace-nowrap">
                        {m.pre_auction_price?.toLocaleString('en-IN')} <span className="text-slate-600">@{m.pre_auction_time}</span>
                      </td>
                      <td className="px-3 py-1.5 text-right text-slate-300 whitespace-nowrap">
                        {m.post_auction_price?.toLocaleString('en-IN')} <span className="text-slate-600">@{m.post_auction_time}</span>
                      </td>
                      <td className={`px-3 py-1.5 text-right font-semibold whitespace-nowrap ${m.move_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {m.move_pct >= 0 ? '+' : ''}{m.move_pct}% ({m.move_abs >= 0 ? '+' : ''}{m.move_abs})
                      </td>
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

function IndexSection({ indexName, showBacktest = true }) {
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
        <h3 className="text-sm font-bold text-white">{DISPLAY_NAME[indexName] || indexName}</h3>
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
          <div className="py-8 text-center text-slate-500 text-sm">Loading {DISPLAY_NAME[indexName] || indexName} snapshots...</div>
        )}
        {!loading && rows.length === 0 && !error && (
          <div className="py-8 text-center text-slate-500 text-sm">
            No snapshots logged yet today. A new one is taken every scan cycle once Fyers is live.
          </div>
        )}
        {error && <div className="py-4 text-center text-rose-400 text-sm">⚠ {error}</div>}

        {rows.length > 0 && (
          <>
            <SnapshotTable rows={rows} showAll={showHistory} onToggleShowAll={() => setShowHistory(v => !v)} />
            {showBacktest && <BacktestSection indexName={indexName} />}
            {showBacktest && <CASMovesSection indexName={indexName} />}
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
        price; "Fut OI" and "Fut OI Chg%" (day-over-day) are now tracked too, via Fyers' Market Depth
        API. Crude oil moved to its own dedicated tab, since it works differently enough (no spot/cash
        index, its own MCX hours, its own options chain) to deserve a separate home rather than being
        squeezed in here.
      </div>
      <IndexSection indexName="NIFTY" />
      <IndexSection indexName="BANKNIFTY" />
    </div>
  );
}
