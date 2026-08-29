import { useEffect, useState } from 'react';
import TabInfoBanner from './TabInfoBanner';

// Relative on purpose -- see the same note in SignalList.jsx / IndexTracker.jsx.
const API_BASE = import.meta.env.VITE_API_URL || '';

const CONTRACTS = [
  { id: 'GOLD', label: 'Gold (Standard)' },
  { id: 'GOLDM', label: 'Gold Mini' },
  { id: 'SILVER', label: 'Silver (Standard)' },
  { id: 'SILVERM', label: 'Silver Mini' },
];

// --- shared formatters, same as IndexTracker.jsx (duplicated rather than
// imported -- keeps this file self-contained, IndexTracker.jsx untouched) ---
function fmt(n) {
  if (n == null || isNaN(n)) return '—';
  return Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 });
}
function fmtOi(n) {
  if (n == null || isNaN(n)) return '—';
  return `${(n / 100000).toFixed(1)}L`;
}
function fmtPct(n, digits = 2) {
  if (n == null || isNaN(n)) return '—';
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`;
}

// Aug 20 2026: same shared badge as IndexTracker.jsx's ConfirmMark --
// duplicated here rather than imported, for the same reason every other
// shared piece in this file is duplicated (see the top-of-file note).
// Same known carried-over limitation too: a "⚠ Neutral but falling/
// rising" verdict currently falls through to the plain "—" dash, same
// as the original 15min column always has.
function ConfirmMark({ value }) {
  const color = value === '✓ Confirmed' ? 'text-emerald-400' : value === '⚠ Conflict' ? 'text-rose-400' : 'text-slate-600';
  const mark = value === '✓ Confirmed' ? '✓' : value === '⚠ Conflict' ? '⚠' : '—';
  return <span className={color}>{mark}</span>;
}

const BIAS_STYLE = {
  'Bullish (Strong)': 'text-emerald-400 bg-emerald-500/15',
  'Bullish': 'text-emerald-400 bg-emerald-500/10',
  'Neutral': 'text-amber-400 bg-amber-500/10',
  'Bearish': 'text-rose-400 bg-rose-500/10',
  'Bearish (Strong)': 'text-rose-400 bg-rose-500/15',
};

// --- icons, same set Analytics.jsx uses (duplicated for the same reason) ---
const IconBarChart = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/></svg>
);
const IconTrendingUp = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
);
const IconTrendingDown = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg>
);
const IconInfo = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
);
const IconChevronDown = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
);
const IconChevronUp = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="18 15 12 9 6 15"/></svg>
);
const IconActivity = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
);
const IconAlertTriangle = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
);

const MetricCard = ({ label, value, description, color }) => {
  const colors = {
    emerald: 'border-emerald-500/20 bg-emerald-500/5', rose: 'border-rose-500/20 bg-rose-500/5',
    blue: 'border-blue-500/20 bg-blue-500/5', amber: 'border-amber-500/20 bg-amber-500/5',
    purple: 'border-purple-500/20 bg-purple-500/5',
  };
  const textColors = {
    emerald: 'text-emerald-400', rose: 'text-rose-400', blue: 'text-blue-400',
    amber: 'text-amber-400', purple: 'text-purple-400',
  };
  return (
    <div className={`border rounded-lg p-4 ${colors[color]}`}>
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold ${textColors[color]} mb-1`}>{value}</div>
      <div className="text-[10px] text-slate-600 leading-tight">{description}</div>
    </div>
  );
};

const GreekExplain = ({ label, value, desc }) => (
  <div className="bg-slate-800/50 rounded-lg p-3">
    <div className="text-xs text-slate-500 mb-1">{label}</div>
    <div className="text-lg font-bold text-white mb-1">{value}</div>
    <div className="text-[10px] text-slate-600">{desc}</div>
  </div>
);

const BuildupCard = ({ title, value, trend, interpretation, color }) => {
  const isUp = trend === 'up';
  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-slate-400">{title}</span>
        {isUp ? <span className="text-emerald-400"><IconTrendingUp /></span> : <span className="text-rose-400"><IconTrendingDown /></span>}
      </div>
      <div className={`text-xl font-bold ${color === 'emerald' ? 'text-emerald-400' : color === 'rose' ? 'text-rose-400' : 'text-blue-400'} mb-2`}>
        {value}
      </div>
      <p className="text-xs text-slate-500 leading-relaxed">{interpretation}</p>
    </div>
  );
};

// --- price / OI / Bias snapshot table -- same shape as IndexTracker.jsx's
// SnapshotTable, but "Spot" column dropped entirely rather than shown
// blank: these commodities have no separate spot/cash index, and here (unlike the
// shared Index Tracker) there's room to just not show a column that will
// never have data, instead of showing a permanent dash. -----------------
function SnapshotTable({ rows, showAll, onToggleShowAll }) {
  const visible = showAll ? rows : rows.slice(0, 1);
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-slate-800/60 text-slate-500 text-[10px] uppercase">
            <th className="text-left px-2.5 py-2 font-medium">Time</th>
            <th className="text-right px-2.5 py-2 font-medium">Price</th>
            <th className="text-right px-2.5 py-2 font-medium">Chg%</th>
            <th className="text-right px-2.5 py-2 font-medium">Fut OI</th>
            <th className="text-right px-2.5 py-2 font-medium">Fut OI Chg%</th>
            <th className="text-right px-2.5 py-2 font-medium">PCR</th>
            <th className="text-right px-2.5 py-2 font-medium">Max Pain</th>
            <th className="text-right px-2.5 py-2 font-medium">Put Wall</th>
            <th className="text-right px-2.5 py-2 font-medium">Call Wall</th>
            <th className="text-right px-2.5 py-2 font-medium">IV%</th>
            <th className="text-right px-2.5 py-2 font-medium" title="Where today's IV ranks against recent history">IV %ile</th>
            <th className="text-center px-2.5 py-2 font-medium">Bias</th>
            <th className="text-center px-2.5 py-2 font-medium" title="15-minute horizon (unchanged from before)">Confirms?</th>
            <th className="text-center px-2.5 py-2 font-medium" title="5-minute horizon">5min</th>
            <th className="text-center px-2.5 py-2 font-medium" title="30-minute horizon">30min</th>
            <th className="text-center px-2.5 py-2 font-medium" title="60-minute horizon">60min</th>
            <th className="text-center px-2.5 py-2 font-medium" title="How many horizons with enough data actually confirm">Horizons</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((r, i) => {
            const isUp = (r['Change %'] || 0) >= 0;
            const confirms = r['Price Confirms Bias'];
            return (
              <tr key={i} className={`border-t border-slate-800/40 ${i === 0 ? 'bg-slate-800/30' : 'hover:bg-slate-800/20'}`}>
                <td className="px-2.5 py-2 text-slate-500 font-mono whitespace-nowrap">{r.Time}</td>
                <td className="px-2.5 py-2 text-right text-white font-semibold whitespace-nowrap"><span className="tier-critical">{fmt(r.Fut)}</span></td>
                <td className={`px-2.5 py-2 text-right whitespace-nowrap ${isUp ? 'text-emerald-400' : 'text-rose-400'}`}>{fmtPct(r['Change %'])}</td>
                <td className="px-2.5 py-2 text-right text-indigo-300 whitespace-nowrap"><span className="tier-secondary">{fmtOi(r['Fut OI'])}</span></td>
                <td className={`px-2.5 py-2 text-right whitespace-nowrap ${(r['Fut OI Chg %'] || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{fmtPct(r['Fut OI Chg %'])}</td>
                <td className="px-2.5 py-2 text-right text-indigo-400 whitespace-nowrap"><span className="tier-important">{r.PCR != null ? r.PCR.toFixed(2) : '—'}</span></td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap"><span className="tier-important">{fmt(r['Max Pain'])}</span></td>
                <td className="px-2.5 py-2 text-right text-emerald-400 whitespace-nowrap"><span className="tier-important">{fmt(r['Highest Put OI Strike'])}</span></td>
                <td className="px-2.5 py-2 text-right text-rose-400 whitespace-nowrap"><span className="tier-important">{fmt(r['Highest Call OI Strike'])}</span></td>
                <td className="px-2.5 py-2 text-right text-amber-400 whitespace-nowrap"><span className="tier-important">{r['IV %'] != null ? `${r['IV %'].toFixed(1)}%` : '—'}</span></td>
                <td className="px-2.5 py-2 text-right text-slate-300 whitespace-nowrap"><span className="tier-secondary">{r['IV %ile'] != null ? `${r['IV %ile']}` : '—'}</span></td>
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

// --- backtest section -- same pattern as IndexTracker.jsx's, works
// unmodified now that IndexBacktestView accepts commodity names too ---
function BacktestSection({ contractId }) {
  const [show, setShow] = useState(false);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!show || data || loading) return;
    setLoading(true);
    fetch(`${API_BASE}/api/index-backtest/${contractId}/`)
      .then(r => r.json())
      .then(d => { setData(d); setError(null); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [show, contractId, data, loading]);

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
        <button onClick={() => setShow(v => !v)} className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors">
          {show ? '▲ Hide' : '▼ Show'} Bias backtest (does it predict price?)
        </button>
        <a href={`${API_BASE}/api/index-backtest/${contractId}/export/`}
          className="text-[11px] font-medium text-indigo-400 bg-indigo-500/10 border border-indigo-500/25 px-2.5 py-1 rounded-lg hover:bg-indigo-500/20 transition-colors shrink-0" download>
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
                    <th className="text-left px-3 py-2">Date</th><th className="text-left px-3 py-2">Bias</th>
                    <th className="text-right px-3 py-2">Hit %</th><th className="text-right px-3 py-2">Samples</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(r => (
                    <tr key={`${r.day}-${r.bias}`} className="border-t border-slate-800/60">
                      <td className="px-3 py-1.5 text-slate-300 whitespace-nowrap">{r.day}</td>
                      <td className="px-3 py-1.5"><span className={`px-1.5 py-0.5 rounded-full text-[10px] whitespace-nowrap ${BIAS_STYLE[r.bias] || 'text-slate-400'}`}>{r.bias}</span></td>
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

// --- options chain -- adapted from Analytics.jsx, no search bar (fixed
// to whichever contract the top toggle picked), otherwise the same
// metric cards / CE|Strike|PE table / Greeks / OI buildup layout. -------
function OptionsChainSection({ contractId, contractLabel }) {
  const [showGreeks, setShowGreeks] = useState(false);
  const [oiData, setOiData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/api/option-analytics/${contractId}/`)
      .then(r => r.json())
      .then(res => {
        if (cancelled) return;
        if (!res.live) {
          setOiData(null);
          setError(res.error || 'No live option chain available for this contract.');
          return;
        }
        setOiData({
          symbol: res.symbol, spot: res.spot,
          pcr: res.pcr != null ? res.pcr.toFixed(2) : '—',
          maxPain: res.maxPain,
          atmIv: res.atmIv != null ? res.atmIv.toFixed(1) : '—',
          atmStrike: res.atmStrike, support: res.support, resistance: res.resistance,
          oiBuildup: res.oiBuildup, atmGreeks: res.greeks || {},
          totalCeOi: res.totalCeOi || 0, totalPeOi: res.totalPeOi || 0,
          ceOiChg: res.ceOiChg || 0, peOiChg: res.peOiChg || 0,
          ceData: (res.ceData || []).map(d => ({
            strike: d.strike, ltp: d.ltp, oi: d.oi,
            oiChg: d.oi_chg_pct != null ? d.oi_chg_pct.toFixed(1) : '0.0',
            iv: d.iv != null ? d.iv.toFixed(1) : '—', volume: d.volume,
            delta: d.delta, gamma: d.gamma, theta: d.theta, vega: d.vega,
          })),
          peData: (res.peData || []).map(d => ({
            strike: d.strike, ltp: d.ltp, oi: d.oi,
            oiChg: d.oi_chg_pct != null ? d.oi_chg_pct.toFixed(1) : '0.0',
            iv: d.iv != null ? d.iv.toFixed(1) : '—', volume: d.volume,
            delta: d.delta, gamma: d.gamma, theta: d.theta, vega: d.vega,
          })),
        });
      })
      .catch(e => { if (!cancelled) { setOiData(null); setError(e.message || 'Failed to load option chain.'); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [contractId]);

  if (loading) {
    return (
      <div className="bg-slate-900 rounded-lg border border-slate-800 p-8 text-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400 mx-auto mb-4" />
        <p className="text-slate-400">Loading options for {contractLabel}...</p>
      </div>
    );
  }
  if (error || !oiData) {
    return (
      <div className="bg-slate-900 rounded-lg border border-slate-800 p-8 text-center">
        <span className="text-amber-400 inline-block mb-3"><IconAlertTriangle /></span>
        <p className="text-slate-300 font-medium mb-1">No live option chain data for {contractLabel}</p>
        <p className="text-slate-500 text-sm">{error}</p>
      </div>
    );
  }

  const { ceData, peData, pcr, maxPain, atmIv, atmStrike, spot } = oiData;

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 rounded-lg border border-slate-800 p-6">
        <div className="flex items-center gap-3 mb-4">
          <span className="text-blue-400"><IconBarChart /></span>
          <div>
            <h2 className="text-xl font-bold text-white">Options Analytics</h2>
            {/* Labeled "Futures" not "Spot" here on purpose -- for a
                commodity the option chain prices off the futures
                contract, and calling it Spot would misleadingly imply
                a separate cash/index price exists the way it does for
                NIFTY. This IS the correct reference price for these
                options, just under an honest name. */}
            <p className="text-sm text-slate-500">{contractLabel} • Futures: ₹{spot.toFixed(2)}</p>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <MetricCard label="Put-Call Ratio (OI)" value={pcr} description=">1 = Bearish bias, <1 = Bullish bias" color={parseFloat(pcr) > 1 ? 'rose' : 'emerald'} />
          <MetricCard label="Max Pain" value={`₹${maxPain}`} description="Strike where option buyers lose most" color="blue" />
          <MetricCard label="ATM Implied Vol" value={`${atmIv}%`} description="Expected price swing (annualized) — approximate for commodities, solved with spot-style Black-Scholes rather than the futures-specific Black-76 model" color="amber" />
          <MetricCard label="ATM Strike" value={`₹${atmStrike}`} description="Nearest strike to the futures price" color="purple" />
        </div>

        <div className="bg-slate-800/30 rounded-lg p-4 mb-6 border border-slate-700/50">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-blue-400"><IconInfo /></span>
            <h3 className="text-sm font-semibold text-white">Understanding Options</h3>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2"><span className="text-emerald-400"><IconTrendingUp /></span><span className="font-semibold text-emerald-400">CE = Call Option</span></div>
              <p className="text-slate-400 text-xs leading-relaxed">
                <strong className="text-slate-300">Bet that price will GO UP.</strong> Buying CE gives you the right to buy at the strike price.
                <span className="block mt-1 text-emerald-400/80">Example: {contractLabel} CE {atmStrike} means "I bet price will go above ₹{atmStrike}"</span>
              </p>
            </div>
            <div className="bg-rose-500/5 border border-rose-500/20 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2"><span className="text-rose-400"><IconTrendingDown /></span><span className="font-semibold text-rose-400">PE = Put Option</span></div>
              <p className="text-slate-400 text-xs leading-relaxed">
                <strong className="text-slate-300">Bet that price will GO DOWN.</strong> Buying PE gives you the right to sell at the strike price.
                <span className="block mt-1 text-rose-400/80">Example: {contractLabel} PE {atmStrike} means "I bet price will fall below ₹{atmStrike}"</span>
              </p>
            </div>
          </div>
        </div>

        <div className="hidden sm:block overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-800 text-slate-400 text-xs uppercase tracking-wider">
                <th className="p-3 text-left rounded-tl-lg"><div className="text-emerald-400 font-bold">CALL (CE)</div><div className="text-[10px] text-slate-500 font-normal">Bullish Bet ↑</div></th>
                <th className="p-3 text-left">LTP</th><th className="p-3 text-left">OI</th><th className="p-3 text-left">OI Chg</th>
                <th className="p-3 text-center bg-slate-700/50"><div className="text-white font-bold">Strike</div><div className="text-[10px] text-slate-500 font-normal">Exercise Price</div></th>
                <th className="p-3 text-right">OI Chg</th><th className="p-3 text-right">OI</th><th className="p-3 text-right">LTP</th>
                <th className="p-3 text-right rounded-tr-lg"><div className="text-rose-400 font-bold">PUT (PE)</div><div className="text-[10px] text-slate-500 font-normal">Bearish Bet ↓</div></th>
              </tr>
            </thead>
            <tbody>
              {ceData.map((ce, idx) => {
                const pe = peData[idx];
                const isATM = ce.strike === atmStrike;
                const ceOiUp = parseFloat(ce.oiChg) > 0;
                const peOiUp = parseFloat(pe.oiChg) > 0;
                return (
                  <tr key={ce.strike} className={`border-t border-slate-700/50 ${isATM ? 'bg-blue-500/5' : ''}`}>
                    <td className="p-3">
                      <div className="flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full ${ceOiUp ? 'bg-emerald-400' : 'bg-rose-400'}`} />
                        <div><div className="text-emerald-400 font-medium">{contractLabel} CE {ce.strike}</div><div className="text-[10px] text-slate-600">IV: {ce.iv}% | Vol: {(ce.volume/1000).toFixed(0)}K</div></div>
                      </div>
                    </td>
                    <td className="p-3 text-emerald-400 font-bold">₹{ce.ltp}</td>
                    <td className="p-3 text-slate-300">{(ce.oi/100000).toFixed(1)}L</td>
                    <td className={`p-3 ${ceOiUp ? 'text-emerald-400' : 'text-rose-400'}`}><div className="flex items-center gap-1">{ceOiUp ? <IconTrendingUp /> : <IconTrendingDown />}{ce.oiChg}%</div></td>
                    <td className={`p-3 text-center font-bold ${isATM ? 'text-blue-400 bg-blue-500/10' : 'text-slate-300'}`}>₹{ce.strike}{isATM && <span className="ml-1 text-[10px] bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded">ATM</span>}</td>
                    <td className={`p-3 text-right ${peOiUp ? 'text-emerald-400' : 'text-rose-400'}`}><div className="flex items-center justify-end gap-1">{peOiUp ? <IconTrendingUp /> : <IconTrendingDown />}{pe.oiChg}%</div></td>
                    <td className="p-3 text-right text-slate-300">{(pe.oi/100000).toFixed(1)}L</td>
                    <td className="p-3 text-right text-rose-400 font-bold">₹{pe.ltp}</td>
                    <td className="p-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div><div className="text-rose-400 font-medium">{contractLabel} PE {pe.strike}</div><div className="text-[10px] text-slate-600">IV: {pe.iv}% | Vol: {(pe.volume/1000).toFixed(0)}K</div></div>
                        <div className={`w-2 h-2 rounded-full ${peOiUp ? 'bg-emerald-400' : 'bg-rose-400'}`} />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="sm:hidden space-y-2">
          {ceData.map((ce, idx) => {
            const pe = peData[idx];
            const isATM = ce.strike === atmStrike;
            const ceOiUp = parseFloat(ce.oiChg) > 0;
            const peOiUp = parseFloat(pe.oiChg) > 0;
            return (
              <div key={ce.strike} className={`rounded-lg border p-3 ${isATM ? 'border-blue-500/40 bg-blue-500/5' : 'border-slate-700/50 bg-slate-800/20'}`}>
                <div className="flex items-center justify-center gap-2 mb-2"><span className="text-white font-bold text-sm">₹{ce.strike}</span>{isATM && <span className="text-[10px] bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded">ATM</span>}</div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="bg-emerald-500/5 border border-emerald-500/20 rounded p-2">
                    <div className="text-[10px] text-emerald-400 font-semibold mb-1">CALL (CE)</div>
                    <div className="text-emerald-400 font-bold">₹{ce.ltp}</div>
                    <div className="text-[10px] text-slate-400 mt-1">OI {(ce.oi/100000).toFixed(1)}L</div>
                    <div className={`text-[10px] flex items-center gap-1 mt-0.5 ${ceOiUp ? 'text-emerald-400' : 'text-rose-400'}`}>{ceOiUp ? <IconTrendingUp /> : <IconTrendingDown />}{ce.oiChg}%</div>
                    <div className="text-[10px] text-slate-600 mt-1">IV {ce.iv}% · Vol {(ce.volume/1000).toFixed(0)}K</div>
                  </div>
                  <div className="bg-rose-500/5 border border-rose-500/20 rounded p-2 text-right">
                    <div className="text-[10px] text-rose-400 font-semibold mb-1">PUT (PE)</div>
                    <div className="text-rose-400 font-bold">₹{pe.ltp}</div>
                    <div className="text-[10px] text-slate-400 mt-1">OI {(pe.oi/100000).toFixed(1)}L</div>
                    <div className={`text-[10px] flex items-center justify-end gap-1 mt-0.5 ${peOiUp ? 'text-emerald-400' : 'text-rose-400'}`}>{peOiUp ? <IconTrendingUp /> : <IconTrendingDown />}{pe.oiChg}%</div>
                    <div className="text-[10px] text-slate-600 mt-1">IV {pe.iv}% · Vol {(pe.volume/1000).toFixed(0)}K</div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-4">
          <button onClick={() => setShowGreeks(!showGreeks)} className="flex items-center gap-2 text-sm text-blue-400 hover:text-blue-300 transition-colors">
            {showGreeks ? <IconChevronUp /> : <IconChevronDown />}{showGreeks ? 'Hide Greeks' : 'Show Greeks (Delta, Gamma, Theta, Vega)'}
          </button>
          {showGreeks && (
            <div className="mt-3 bg-slate-800/30 rounded-lg p-4 border border-slate-700/50">
              <p className="text-xs text-slate-500 mb-3">ATM strike ₹{atmStrike} — CE (call) Greeks</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <GreekExplain label="Delta" value={oiData.atmGreeks?.CE?.delta ?? '—'} desc="Price change per ₹1 move in underlying" />
                <GreekExplain label="Gamma" value={oiData.atmGreeks?.CE?.gamma ?? '—'} desc="Rate of Delta change" />
                <GreekExplain label="Theta" value={oiData.atmGreeks?.CE?.theta ?? '—'} desc="Daily time decay (loss)" />
                <GreekExplain label="Vega" value={oiData.atmGreeks?.CE?.vega ?? '—'} desc="Price change per 1% IV move" />
              </div>
              <p className="text-xs text-slate-500 mb-3">ATM strike ₹{atmStrike} — PE (put) Greeks</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <GreekExplain label="Delta" value={oiData.atmGreeks?.PE?.delta ?? '—'} desc="Price change per ₹1 move in underlying" />
                <GreekExplain label="Gamma" value={oiData.atmGreeks?.PE?.gamma ?? '—'} desc="Rate of Delta change" />
                <GreekExplain label="Theta" value={oiData.atmGreeks?.PE?.theta ?? '—'} desc="Daily time decay (loss)" />
                <GreekExplain label="Vega" value={oiData.atmGreeks?.PE?.vega ?? '—'} desc="Price change per 1% IV move" />
              </div>
              <div className="text-xs text-slate-500 bg-slate-800/50 rounded p-3">
                <span className="inline-block mr-1 text-amber-400"><IconAlertTriangle /></span>
                <strong className="text-slate-400">Pro Tip:</strong> High Gamma near ATM means your Delta changes fast — profits/losses accelerate. High Theta means you're losing money every day just from time passing.
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="bg-slate-900 rounded-lg border border-slate-800 p-6">
        <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2"><span className="text-purple-400"><IconActivity /></span>OI Buildup Analysis</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <BuildupCard title="CE OI Buildup" value={`${(oiData.totalCeOi/100000).toFixed(1)}L`} trend="up" interpretation="High CE OI at resistance = Strong wall. Breakout above this level is powerful." color="emerald" />
          <BuildupCard title="PE OI Buildup" value={`${(oiData.totalPeOi/100000).toFixed(1)}L`} trend="up" interpretation="High PE OI at support = Floor established. Bounce likely from this zone." color="rose" />
          <BuildupCard title="Net OI Change" value={parseFloat(pcr) > 1 ? 'PE Heavy' : 'CE Heavy'} trend={parseFloat(pcr) > 1 ? 'down' : 'up'} interpretation={parseFloat(pcr) > 1 ? 'Writers are selling more Puts = Bullish stance (support expected)' : 'Writers are selling more Calls = Bearish stance (resistance expected)'} color={parseFloat(pcr) > 1 ? 'emerald' : 'rose'} />
        </div>
      </div>
    </div>
  );
}

// --- top-level: contract toggle + summary/backtest + options chain ---
export default function BullionTracker() {
  const [contractId, setContractId] = useState('GOLD');
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showHistory, setShowHistory] = useState(false);
  const [selectedDate, setSelectedDate] = useState(''); // '' means today
  const [availableDates, setAvailableDates] = useState([]);

  const contractLabel = CONTRACTS.find(c => c.id === contractId)?.label || contractId;

  // Fetched whenever the contract changes -- which past dates actually
  // have logged data for THIS contract specifically (GOLD, GOLDM, SILVER,
  // and SILVERM all log separately, so their available dates can differ).
  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/api/index-tracker/${contractId}/dates/`)
      .then(r => r.json())
      .then(d => { if (!cancelled) setAvailableDates(d.dates || []); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [contractId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setShowHistory(false);
    const load = () => {
      const url = selectedDate
        ? `${API_BASE}/api/index-tracker/${contractId}/?date=${selectedDate}`
        : `${API_BASE}/api/index-tracker/${contractId}/`;
      fetch(url)
        .then(r => r.json())
        .then(data => { if (!cancelled) { setRows(data.snapshots || []); setError(null); } })
        .catch(e => { if (!cancelled) setError(e.message); })
        .finally(() => { if (!cancelled) setLoading(false); });
    };
    load();
    // Only auto-refresh when viewing today -- a past date's data is
    // finished and won't change.
    if (!selectedDate) {
      const interval = setInterval(load, 60000);
      return () => { cancelled = true; clearInterval(interval); };
    }
    return () => { cancelled = true; };
  }, [contractId, selectedDate]);

  return (
    <div className="space-y-4">
      <TabInfoBanner>
        Gold and Silver have their own dedicated tab, same reasoning as Crude Oil — no separate spot/cash index
        (the futures contract IS the underlying), their own MCX trading hours, their own options chain below.
        Unlike Crude, these don't trade in every calendar month — the front-month resolver checks live Fyers
        data to find whichever contract is actually active right now, rather than assuming a fixed monthly cycle.
      </TabInfoBanner>

      <div className="flex gap-1 bg-slate-900/50 p-1 rounded-xl w-fit">
        {CONTRACTS.map(c => (
          <button key={c.id} onClick={() => { setContractId(c.id); setSelectedDate(''); }}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${contractId === c.id ? 'bg-slate-700 text-white shadow-lg' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'}`}>
            {c.label}
          </button>
        ))}
      </div>

      <div className="bg-slate-900/50 rounded-xl border border-slate-800 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 gap-3">
          <h3 className="text-sm font-bold text-white whitespace-nowrap">{contractLabel}</h3>
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
            <a href={`${API_BASE}/api/index-tracker/${contractId}/export/`}
              className="text-[11px] font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/25 px-2.5 py-1 rounded-lg hover:bg-emerald-500/20 transition-colors whitespace-nowrap" download>
              📥 Export
            </a>
          </div>
        </div>
        <div className="p-4">
          {loading && rows.length === 0 && <div className="py-8 text-center text-slate-500 text-sm">Loading {contractLabel} snapshots...</div>}
          {!loading && rows.length === 0 && !error && (
            <div className="py-8 text-center text-slate-500 text-sm">
              {selectedDate
                ? `Nothing logged on ${selectedDate}.`
                : 'No snapshots logged yet today. A new one is taken roughly every minute while MCX is open.'}
            </div>
          )}
          {error && <div className="py-4 text-center text-rose-400 text-sm">⚠ {error}</div>}
          {rows.length > 0 && (
            <>
              <SnapshotTable rows={rows} showAll={showHistory} onToggleShowAll={() => setShowHistory(v => !v)} />
              <BacktestSection contractId={contractId} />
            </>
          )}
        </div>
      </div>

      <OptionsChainSection contractId={contractId} contractLabel={contractLabel} />

      <div className="text-center text-[11px] text-slate-600 pt-1 pb-2">
        MCX trading hours: ~9:00 AM – 11:30 PM IST, Monday–Friday (approximate — doesn't account for MCX-specific holidays)
      </div>
    </div>
  );
}
