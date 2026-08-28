import { useEffect, useState } from 'react';
import MarketHeatmap from './MarketHeatmap';
import MarketSummary from './MarketSummary';
import IndicesPerformance from './IndicesPerformance';

// Relative on purpose -- see the same note in IndexTracker.jsx/SignalList.jsx.
const API_BASE = import.meta.env.VITE_API_URL || '';

// Aug 21 2026: this is a DELIBERATELY separate, leaner view from
// IndexTracker.jsx -- that table grew to 25 columns over tonight
// (multi-horizon confirmation, IV%ile, OI buildup, etc.), which is
// genuinely useful but not what was being asked for here. This
// component shows exactly the 15 columns of a specific reference
// tool, nothing more, nothing computed differently -- same backend
// data (/api/index-tracker/<name>/), same fields, just a narrower
// slice of them in the reference's exact column order. No backend
// changes needed for this at all; every field here already existed.

const BIAS_DOT = {
  'Bullish (Strong)': 'bg-emerald-500',
  'Bullish': 'bg-emerald-500',
  'Neutral': 'bg-amber-400',
  'Bearish': 'bg-rose-500',
  'Bearish (Strong)': 'bg-rose-500',
};

const DISPLAY_NAME = { NIFTY: 'NIFTY', BANKNIFTY: 'BANKNIFTY' };

function fmt(n, digits = 2) {
  if (n === null || n === undefined || isNaN(n)) return '—';
  return Number(n).toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function fmtOi(n) {
  if (n === null || n === undefined || isNaN(n)) return '—';
  return `${(n / 100000).toFixed(1)} L`;
}

function fmtStrikeOi(strike, value) {
  if (strike === null || strike === undefined) return '—';
  return `${fmt(strike, 0)}, ${fmtOi(value)}`;
}

// Directional arrow comparing this row's value to the PREVIOUS row's
// (chronologically earlier -- since rows are most-recent-first, that's
// the next array index). Matches the reference tool's own up/down
// arrows next to changed values. No arrow (just the value) if there's
// nothing earlier to compare against, or the value is unchanged.
function Arrow({ value }) {
  if (value === null || value === undefined) return null;
  if (value > 0) return <span className="text-emerald-400 ml-0.5">↑</span>;
  if (value < 0) return <span className="text-rose-400 ml-0.5">↓</span>;
  return <span className="text-slate-500 ml-0.5">→</span>;
}

// Aug 21 2026: he explicitly wants this tab at the reference tool's own
// ~30-min cadence, not the full ~60s logging density -- Index Tracker
// already covers full density; this is deliberately the sparser view.
// Rows come back most-recent-first from the API; walk chronologically
// (oldest first) and greedily keep a row only once at least
// intervalMinutes has passed since the last KEPT row, then reverse back
// to most-recent-first for display. Greedy-since-last-kept (not a fixed
// clock-aligned bucket like :00/:30) so it's robust to the real
// snapshot cadence drifting a little cycle to cycle, same as it visibly
// does in his own screenshots (13:04:17, 13:03:11, 13:02:06 -- not
// exactly 60s apart).
function parseTimeToMinutes(timeStr) {
  if (!timeStr) return null;
  const [h, m] = timeStr.split(':').map(Number);
  if (isNaN(h) || isNaN(m)) return null;
  return h * 60 + m;
}

function downsampleToInterval(rows, intervalMinutes = 30) {
  const chronological = [...rows].reverse();
  const kept = [];
  let lastKeptMinutes = null;
  for (const row of chronological) {
    const t = parseTimeToMinutes(row.Time);
    if (t === null) continue;
    if (lastKeptMinutes === null || t - lastKeptMinutes >= intervalMinutes) {
      kept.push(row);
      lastKeptMinutes = t;
    }
  }
  return kept.reverse();
}

// Aug 24 2026: client-side download button, no backend involved -- this
// exports exactly the rows the table is showing (post-downsample, same
// date filter as the screen) using the same fmt/fmtOi/fmtStrikeOi
// helpers the table itself uses, so the CSV matches what's on screen
// rather than raw/differently-rounded backend values.
function DownloadIcon({ className = 'w-3.5 h-3.5' }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M12 3v12" />
      <path d="M7 10l5 5 5-5" />
      <path d="M5 21h14" />
    </svg>
  );
}

const CSV_HEADERS = [
  'Time', 'Spot', 'Fut', 'PCR', 'ATM',
  'Highest Put OI (strike,L)', 'Highest Call OI (strike,L)',
  'ATM Put OI', 'ATM Call OI', 'IV', 'IV %ile', 'VIX', 'Max Pain',
  'Fut OI Chg', 'Bias',
];

function toCsvCell(value) {
  if (value === null || value === undefined) return '';
  const s = String(value);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function rowToCsvValues(r) {
  return [
    r.Time,
    fmt(r.Spot),
    fmt(r.Fut),
    r.PCR != null ? r.PCR.toFixed(2) : '',
    fmt(r['ATM Strike'], 0),
    fmtStrikeOi(r['Highest Put OI Strike'], r['Highest Put OI Value']),
    fmtStrikeOi(r['Highest Call OI Strike'], r['Highest Call OI Value']),
    fmtOi(r['Put OI (ATM)']),
    fmtOi(r['Call OI (ATM)']),
    r['IV %'] != null ? r['IV %'].toFixed(1) : '',
    r['IV %ile'] != null ? r['IV %ile'] : '',
    fmt(r.VIX, 1),
    fmt(r['Max Pain'], 0),
    r['Fut OI Chg %'] != null ? `${r['Fut OI Chg %'].toFixed(1)}%` : '',
    r.Bias || '',
  ];
}

function downloadCsv(indexName, dateLabel, rows) {
  const lines = [CSV_HEADERS.join(',')];
  for (const r of rows) {
    lines.push(rowToCsvValues(r).map(toCsvCell).join(','));
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `MarketView_${indexName}_${dateLabel}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function MarketViewTable({ rows }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-slate-500 border-b border-slate-800">
            <th className="text-left px-2.5 py-2 font-medium">Time</th>
            <th className="text-right px-2.5 py-2 font-medium">Spot</th>
            <th className="text-right px-2.5 py-2 font-medium">Fut</th>
            <th className="text-right px-2.5 py-2 font-medium">PCR</th>
            <th className="text-right px-2.5 py-2 font-medium">ATM</th>
            <th className="text-right px-2.5 py-2 font-medium">Highest Put OI (strike,L)</th>
            <th className="text-right px-2.5 py-2 font-medium">Highest Call OI (strike,L)</th>
            <th className="text-right px-2.5 py-2 font-medium">ATM Put OI</th>
            <th className="text-right px-2.5 py-2 font-medium">ATM Call OI</th>
            <th className="text-right px-2.5 py-2 font-medium">IV</th>
            <th className="text-right px-2.5 py-2 font-medium" title="Where today's IV ranks against recent history">IV %ile</th>
            <th className="text-right px-2.5 py-2 font-medium">VIX</th>
            <th className="text-right px-2.5 py-2 font-medium">Max Pain</th>
            <th className="text-right px-2.5 py-2 font-medium">Fut OI Chg</th>
            <th className="text-center px-2.5 py-2 font-medium">Bias</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const prev = rows[i + 1]; // chronologically earlier row, for the up/down arrows
            const delta = (key) => (prev && r[key] != null && prev[key] != null ? r[key] - prev[key] : null);
            return (
              <tr key={r.Time + i} className="border-b border-slate-800/60 hover:bg-slate-800/30 transition-colors">
                <td className="px-2.5 py-2 text-slate-400 whitespace-nowrap">{r.Time}</td>
                <td className="px-2.5 py-2 text-right text-white font-medium whitespace-nowrap">{fmt(r.Spot)}<Arrow value={delta('Spot')} /></td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap">{fmt(r.Fut)}<Arrow value={delta('Fut')} /></td>
                <td className="px-2.5 py-2 text-right text-indigo-400 whitespace-nowrap">{r.PCR != null ? r.PCR.toFixed(2) : '—'}<Arrow value={delta('PCR')} /></td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap">{fmt(r['ATM Strike'], 0)}</td>
                <td className="px-2.5 py-2 text-right text-emerald-400 whitespace-nowrap">{fmtStrikeOi(r['Highest Put OI Strike'], r['Highest Put OI Value'])}<Arrow value={delta('Highest Put OI Value')} /></td>
                <td className="px-2.5 py-2 text-right text-rose-400 whitespace-nowrap">{fmtStrikeOi(r['Highest Call OI Strike'], r['Highest Call OI Value'])}<Arrow value={delta('Highest Call OI Value')} /></td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap">{fmtOi(r['Put OI (ATM)'])}<Arrow value={delta('Put OI (ATM)')} /></td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap">{fmtOi(r['Call OI (ATM)'])}<Arrow value={delta('Call OI (ATM)')} /></td>
                <td className="px-2.5 py-2 text-right text-amber-400 whitespace-nowrap">{r['IV %'] != null ? r['IV %'].toFixed(1) : '—'}<Arrow value={delta('IV %')} /></td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap">{r['IV %ile'] != null ? r['IV %ile'] : '—'}<Arrow value={delta('IV %ile')} /></td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap">{fmt(r.VIX, 1)}<Arrow value={delta('VIX')} /></td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap">{fmt(r['Max Pain'], 0)}<Arrow value={delta('Max Pain')} /></td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap">{r['Fut OI Chg %'] != null ? `${r['Fut OI Chg %'].toFixed(1)}%` : '—'}<Arrow value={delta('Fut OI Chg %')} /></td>
                <td className="px-2.5 py-2 text-center whitespace-nowrap">
                  <span className="inline-flex items-center gap-1.5">
                    <span className={`w-2 h-2 rounded-full ${BIAS_DOT[r.Bias] || 'bg-slate-500'}`} />
                    <span className="text-slate-300">{r.Bias || '—'}</span>
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function MarketViewSection({ indexName }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedDate, setSelectedDate] = useState('');
  const [availableDates, setAvailableDates] = useState([]);

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
          {rows.length > 0 && (
            <button
              type="button"
              onClick={() => downloadCsv(indexName, selectedDate || new Date().toISOString().slice(0, 10), downsampleToInterval(rows, 30))}
              title="Export this table as CSV"
              className="flex items-center gap-1.5 text-[11px] font-medium bg-slate-900/60 border border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/10 hover:border-emerald-500/60 rounded-full px-3 py-1.5 transition-colors"
            >
              <DownloadIcon />
              <span>Export</span>
            </button>
          )}
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
        </div>
      </div>

      <div className="p-4">
        {loading && rows.length === 0 && (
          <div className="py-8 text-center text-slate-500 text-sm">Loading {DISPLAY_NAME[indexName] || indexName}...</div>
        )}
        {!loading && rows.length === 0 && !error && (
          <div className="py-8 text-center text-slate-500 text-sm">
            {selectedDate ? `Nothing logged on ${selectedDate}.` : 'No snapshots logged yet today.'}
          </div>
        )}
        {error && <div className="py-4 text-center text-rose-400 text-sm">⚠ {error}</div>}
        {rows.length > 0 && <MarketViewTable rows={downsampleToInterval(rows, 30)} />}
      </div>
    </div>
  );
}

export default function MarketView() {
  return (
    <div className="space-y-4">
      {/* Aug 28 2026: new sections, from the Module 4 (Market View)
          redesign reference -- MarketSummary is pure client-side time
          logic (no backend), MarketHeatmap and IndicesPerformance each
          have their own backend endpoints (see their own files).
          Everything below this (the indigo note + both NIFTY/
          BANKNIFTY tables) is unchanged. */}
      <MarketSummary />
      <MarketHeatmap />
      <IndicesPerformance />
      <div className="bg-indigo-500/10 border border-indigo-500/20 rounded-lg px-4 py-2.5 text-xs text-indigo-300">
        Clean market view — same live data as Index Tracker, just the core columns only, thinned to a
        ~30-minute cadence (Index Tracker still shows every snapshot at full density). Arrows show the
        change from the previous row shown here, not necessarily the immediately-prior raw snapshot.
      </div>
      <MarketViewSection indexName="NIFTY" />
      <MarketViewSection indexName="BANKNIFTY" />
    </div>
  );
}
