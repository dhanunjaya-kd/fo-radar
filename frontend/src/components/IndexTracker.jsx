import { useEffect, useState } from 'react';
import IndexPriceChart from './IndexPriceChart';
import OHLCInfo from './OHLCInfo';
import TabInfoBanner from './TabInfoBanner';
import AdvanceDeclineDonut from './AdvanceDeclineDonut';

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

// Aug 20 2026: shared by the existing 15min "Confirms?" column and the
// 3 new horizon columns below (multi-horizon confirmation, accuracy
// backlog #5) -- same simple ✓/⚠/— rendering everywhere rather than a
// different treatment for the new ones. Known carried-over limitation:
// a "⚠ Neutral but falling/rising" verdict from the backend currently
// falls through to the plain "—" no-data dash here, same as the
// original 15min column always has -- not something this change
// touches, just flagging it since it now applies to 4 columns instead
// of 1.
function ConfirmMark({ value }) {
  const color = value === '✓ Confirmed' ? 'text-emerald-400' : value === '⚠ Conflict' ? 'text-rose-400' : 'text-slate-600';
  const mark = value === '✓ Confirmed' ? '✓' : value === '⚠ Conflict' ? '⚠' : '—';
  return <span className={color}>{mark}</span>;
}

// Aug 21 2026: unified with MarketView.jsx's own Arrow component --
// this table previously used a DIFFERENT arrow source just for ATM
// Put/Call OI (Put Status/Call Status, backend-computed "Writing"/
// "Unwinding" labels). Replaced with the same row-to-row delta
// comparison MarketView.jsx already uses for every column, so both
// tables behave identically rather than running two separate arrow
// systems that could subtly disagree. Directional arrow comparing
// this row's value to the PREVIOUS row's (chronologically earlier --
// since rows are most-recent-first, that's the next array index). No
// arrow if there's nothing earlier to compare against, or the value
// is unchanged.
function Arrow({ value }) {
  if (value === null || value === undefined) return null;
  if (value > 0) return <span className="text-emerald-400 ml-0.5">↑</span>;
  if (value < 0) return <span className="text-rose-400 ml-0.5">↓</span>;
  return <span className="text-slate-500 ml-0.5">→</span>;
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
            <th className="text-right px-2.5 py-2 font-medium">Futures</th>
            <th className="text-right px-2.5 py-2 font-medium">Fut OI</th>
            <th className="text-right px-2.5 py-2 font-medium">Fut OI Chg%</th>
            <th className="text-right px-2.5 py-2 font-medium">VIX</th>
            <th className="text-right px-2.5 py-2 font-medium">IV%</th>
            <th className="text-right px-2.5 py-2 font-medium" title="Where today's IV ranks against recent history">IV %ile</th>
            <th className="text-right px-2.5 py-2 font-medium">PCR</th>
            <th className="text-right px-2.5 py-2 font-medium">Max Pain</th>
            <th className="text-right px-2.5 py-2 font-medium">ATM Put OI</th>
            <th className="text-right px-2.5 py-2 font-medium">ATM Call OI</th>
            <th className="text-right px-2.5 py-2 font-medium" title="Total across the whole chain, not just ATM">Total Put OI</th>
            <th className="text-right px-2.5 py-2 font-medium" title="Total across the whole chain, not just ATM">Total Call OI</th>
            <th className="text-center px-2.5 py-2 font-medium">Bias</th>
            <th className="text-center px-2.5 py-2 font-medium" title="15-minute horizon (unchanged from before)">Confirms?</th>
            <th className="text-center px-2.5 py-2 font-medium" title="5-minute horizon">5min</th>
            <th className="text-center px-2.5 py-2 font-medium" title="30-minute horizon">30min</th>
            <th className="text-center px-2.5 py-2 font-medium" title="60-minute horizon">60min</th>
            <th className="text-center px-2.5 py-2 font-medium" title="How many horizons with enough data actually confirm">Horizons</th>
            <th className="text-right px-2.5 py-2 font-medium">Support</th>
            <th className="text-right px-2.5 py-2 font-medium">Resistance</th>
            <th className="text-right px-2.5 py-2 font-medium">ATM Strike</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((r, i) => {
            const isUp = (r['Change %'] || 0) >= 0;
            const confirms = r['Price Confirms Bias'];
            // rows[i+1], not visible[i+1] -- the chronologically-earlier
            // reference row must come from the FULL fetched set, not just
            // what's currently displayed. When collapsed (showAll=false),
            // visible only has 1 row, but rows still has up to 100 -- this
            // keeps the top row's arrow correct even when older rows
            // aren't shown at all, same reasoning MarketView.jsx documents.
            const prev = rows[i + 1];
            const delta = (key) => (prev && r[key] != null && prev[key] != null ? r[key] - prev[key] : null);
            return (
              <tr key={i} className={`border-t border-slate-800/40 ${i === 0 ? 'bg-slate-800/30' : 'hover:bg-slate-800/20'}`}>
                <td className="px-2.5 py-2 text-slate-500 font-mono whitespace-nowrap">{r.Time}</td>
                <td className="px-2.5 py-2 text-right text-white font-semibold whitespace-nowrap"><span className="tier-critical">{fmt(r.Spot)}</span><Arrow value={delta('Spot')} /></td>
                <td className={`px-2.5 py-2 text-right whitespace-nowrap ${isUp ? 'text-emerald-400' : 'text-rose-400'}`}>{fmtPct(r['Change %'])}</td>
                <td className="px-2.5 py-2 text-right text-indigo-300 whitespace-nowrap"><span className="tier-secondary">{fmt(r.Fut)}</span><Arrow value={delta('Fut')} /></td>
                <td className="px-2.5 py-2 text-right text-indigo-300 whitespace-nowrap"><span className="tier-secondary">{fmtOi(r['Fut OI'])}</span><Arrow value={delta('Fut OI')} /></td>
                <td className={`px-2.5 py-2 text-right whitespace-nowrap ${(r['Fut OI Chg %'] || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{fmtPct(r['Fut OI Chg %'])}</td>
                <td className="px-2.5 py-2 text-right text-orange-400 whitespace-nowrap"><span className="tier-important">{r.VIX != null ? r.VIX.toFixed(2) : '—'}</span><Arrow value={delta('VIX')} /></td>
                <td className="px-2.5 py-2 text-right text-amber-400 whitespace-nowrap"><span className="tier-important">{r['IV %'] != null ? `${r['IV %'].toFixed(1)}%` : '—'}</span><Arrow value={delta('IV %')} /></td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap"><span className="tier-secondary">{r['IV %ile'] != null ? `${r['IV %ile']}` : '—'}</span><Arrow value={delta('IV %ile')} /></td>
                <td className="px-2.5 py-2 text-right text-indigo-400 whitespace-nowrap"><span className="tier-important">{r.PCR != null ? r.PCR.toFixed(2) : '—'}</span><Arrow value={delta('PCR')} /></td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap"><span className="tier-important">{fmt(r['Max Pain'])}</span><Arrow value={delta('Max Pain')} /></td>
                <td className="px-2.5 py-2 text-right text-emerald-400 whitespace-nowrap"><span className="tier-secondary">{fmtOi(r['Put OI (ATM)'])}</span><Arrow value={delta('Put OI (ATM)')} /></td>
                <td className="px-2.5 py-2 text-right text-rose-400 whitespace-nowrap"><span className="tier-secondary">{fmtOi(r['Call OI (ATM)'])}</span><Arrow value={delta('Call OI (ATM)')} /></td>
                <td className="px-2.5 py-2 text-right text-emerald-400 whitespace-nowrap"><span className="tier-secondary">{fmtOi(r['Total Put OI'])}</span><Arrow value={delta('Total Put OI')} /></td>
                <td className="px-2.5 py-2 text-right text-rose-400 whitespace-nowrap"><span className="tier-secondary">{fmtOi(r['Total Call OI'])}</span><Arrow value={delta('Total Call OI')} /></td>
                <td className="px-2.5 py-2 text-center">
                  <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-semibold whitespace-nowrap ${BIAS_STYLE[r.Bias] || 'text-slate-400 bg-slate-700/30'}`}>
                    {r.Bias || '—'}
                  </span>
                </td>
                <td className="px-2.5 py-2 text-center">
                  <ConfirmMark value={confirms} />
                </td>
                <td className="px-2.5 py-2 text-center">
                  <ConfirmMark value={r['Confirms 5min']} />
                </td>
                <td className="px-2.5 py-2 text-center">
                  <ConfirmMark value={r['Confirms 30min']} />
                </td>
                <td className="px-2.5 py-2 text-center">
                  <ConfirmMark value={r['Confirms 60min']} />
                </td>
                <td className="px-2.5 py-2 text-center text-slate-300 font-mono whitespace-nowrap">
                  {r['Horizons Confirming'] || '—'}
                </td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap"><span className="tier-important">{fmt(r.Support)}</span><Arrow value={delta('Support')} /></td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap"><span className="tier-important">{fmt(r.Resistance)}</span><Arrow value={delta('Resistance')} /></td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap"><span className="tier-secondary">{fmt(r['ATM Strike'])}</span><Arrow value={delta('ATM Strike')} /></td>
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
  const [selectedDate, setSelectedDate] = useState(''); // '' means today
  const [availableDates, setAvailableDates] = useState([]);

  // Fetched once -- which past dates actually have logged data, so the
  // dropdown only ever offers real choices instead of letting someone
  // pick a date with nothing behind it.
  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/api/index-tracker/${indexName}/dates/`)
      .then(r => r.json())
      .then(d => { if (!cancelled) setAvailableDates(d.dates || []); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [indexName]);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      const url = selectedDate
        ? `${API_BASE}/api/index-tracker/${indexName}/?date=${selectedDate}`
        : `${API_BASE}/api/index-tracker/${indexName}/`;
      fetch(url)
        .then(r => r.json())
        .then(data => {
          if (cancelled) return;
          setRows(data.snapshots || []);
          setError(null);
        })
        .catch(e => { if (!cancelled) setError(e.message); })
        .finally(() => { if (!cancelled) setLoading(false); });
    };
    setLoading(true);
    load();
    // Only auto-refresh when viewing today -- a past date's data is
    // finished and won't change, so polling it every minute would just
    // be wasted requests.
    if (!selectedDate) {
      const interval = setInterval(load, 60000);
      return () => { cancelled = true; clearInterval(interval); };
    }
    return () => { cancelled = true; };
  }, [indexName, selectedDate]);

  return (
    <div className="bg-slate-900/50 rounded-xl border border-slate-800 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 gap-3">
        <h3 className="text-sm font-bold text-white whitespace-nowrap">{DISPLAY_NAME[indexName] || indexName}</h3>
        <div className="flex items-center gap-2">
          {availableDates.length > 0 && (
            <select
              value={selectedDate}
              onChange={e => setSelectedDate(e.target.value)}
              className="text-[11px] bg-slate-800 border border-slate-700 text-slate-300 rounded-lg px-2 py-1 focus:outline-none focus:border-slate-500"
            >
              <option value="">Today</option>
              {availableDates.map(d => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          )}
          <a
            href={`${API_BASE}/api/index-tracker/${indexName}/export/`}
            className="text-[11px] font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/25 px-2.5 py-1 rounded-lg hover:bg-emerald-500/20 transition-colors whitespace-nowrap"
            download
          >
            📥 Export
          </a>
        </div>
      </div>

      {/* Aug 28 2026: new price chart, from the Module 5 (Index
          Tracker) redesign reference -- own component, own file, no
          backend changes (reuses the same dates/snapshots endpoints
          this section already fetches from). Everything below this
          (the full snapshot table, Bias backtest, CAS moves) is
          unchanged. */}
      <div className="px-4 pt-4">
        <IndexPriceChart indexName={indexName} />
        <div className="mt-3">
          <OHLCInfo indexName={indexName} />
        </div>
      </div>

      <div className="p-4">
        {loading && rows.length === 0 && (
          <div className="py-8 text-center text-slate-500 text-sm">Loading {DISPLAY_NAME[indexName] || indexName} snapshots...</div>
        )}
        {!loading && rows.length === 0 && !error && (
          <div className="py-8 text-center text-slate-500 text-sm">
            {selectedDate
              ? `Nothing logged on ${selectedDate}.`
              : 'No snapshots logged yet today. A new one is taken every scan cycle once Fyers is live.'}
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
      <TabInfoBanner>
        NIFTY and BANKNIFTY only, snapshotted every scan cycle. "Fut" is the real front-month futures
        price; "Fut OI" and "Fut OI Chg%" (day-over-day) are now tracked too, via Fyers' Market Depth
        API. Crude oil moved to its own dedicated tab, since it works differently enough (no spot/cash
        index, its own MCX hours, its own options chain) to deserve a separate home rather than being
        squeezed in here.
      </TabInfoBanner>
      {/* Aug 28 2026: market-wide, not index-specific (same reasoning
          as keeping MarketBanner/MarketBreadth global rather than
          per-tab) -- shown once here, not duplicated inside each
          IndexSection card below. */}
      <div className="bg-slate-900/50 rounded-xl border border-slate-800 p-4">
        <h3 className="text-sm font-bold text-white mb-3">Advances / Declines</h3>
        <AdvanceDeclineDonut />
      </div>
      <IndexSection indexName="NIFTY" />
      <IndexSection indexName="BANKNIFTY" />
    </div>
  );
}
