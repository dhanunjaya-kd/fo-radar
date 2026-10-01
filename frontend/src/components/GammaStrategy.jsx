import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Sep 30 2026: same download icon/button style as SignalList.jsx's
// existing export control -- reused directly for visual consistency,
// per explicit "existing project-standard download button" instruction.
const IconDownload = ({ size = 16 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
);

// Sep 23 2026: Gamma Blast Strategy tab -- separate block, direct
// request, own sidebar entry (not folded into Sniper Signals).
//
// Sep 23 2026 (later same day): active_options/microstructure_alerts
// FIXED here -- the backend (GammaStrategyView) was updated to return
// real data for both (options resolver + microstructure daemon wired
// in), but this component was never updated to actually read either
// field -- it unconditionally rendered two hardcoded "PENDING" blocks
// regardless of what the API returned. Real bug, not a backend issue;
// caught from a screenshot showing PENDING while the backend logs
// showed the options/microstructure cycle actually running. Now reads
// data.active_options.status / data.microstructure_alerts.status
// ("LIVE" vs "WARMING_UP", set by the backend, not guessed here) and
// renders real cards once either goes LIVE.

function fmtPct(n) {
  if (n == null) return '—';
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`;
}

function StockRow({ stock, side }) {
  const isRes = side === 'resistance';
  const badgeColor = isRes ? 'text-emerald-400 bg-emerald-500/10' : 'text-rose-400 bg-rose-500/10';
  const optionLabel = isRes ? 'CE' : 'PE';
  const breakoutStatus = stock.status?.includes('BREAKOUT') || stock.status?.includes('BREAKDOWN');

  return (
    <div className="rounded-lg bg-slate-900/40 border border-slate-700/40 p-3">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-white">{stock.symbol}</span>
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${badgeColor}`}>{optionLabel}</span>
          {breakoutStatus && (
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded text-amber-400 bg-amber-500/10">ACTIVE</span>
          )}
        </div>
        <span className="text-sm text-white font-medium">₹{stock.cmp?.toLocaleString('en-IN')}</span>
      </div>
      <div className="flex items-center justify-between text-[11px] text-slate-400">
        <span>Zone ₹{stock.zone_bottom?.toLocaleString('en-IN')}–₹{stock.zone_top?.toLocaleString('en-IN')}</span>
        <span>{fmtPct(stock.distance_pct)} away</span>
      </div>
      <div className="flex items-center gap-3 mt-1.5 text-[10px]">
        <span className={stock.trend_aligned ? 'text-emerald-400' : 'text-slate-500'}>
          {stock.trend_aligned ? '✓' : '✗'} 50 EMA {isRes ? 'above' : 'below'}
        </span>
        <span className={stock.intraday_momentum ? 'text-emerald-400' : 'text-slate-500'}>
          {stock.intraday_momentum ? '✓' : '✗'} Momentum
        </span>
      </div>
    </div>
  );
}

const TIER_COLOR = { GOLD: 'text-amber-400 bg-amber-500/10', SILVER: 'text-slate-300 bg-slate-400/10', STANDARD: 'text-slate-500 bg-slate-500/10' };

function OptionRow({ opt }) {
  const isCe = opt.option_type === 'CE';
  const sideColor = isCe ? 'text-emerald-400 bg-emerald-500/10' : 'text-rose-400 bg-rose-500/10';
  return (
    <div className="rounded-lg bg-slate-900/40 border border-slate-700/40 p-3">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-white">{opt.symbol}</span>
          <span className="text-xs text-slate-300">{opt.strike} {opt.option_type}</span>
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${sideColor}`}>{opt.option_type}</span>
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${TIER_COLOR[opt.tier] || TIER_COLOR.STANDARD}`}>{opt.tier}</span>
        </div>
        <span className="text-sm text-white font-medium">₹{opt.ltp?.toFixed(2)}</span>
      </div>
      <div className="flex items-center justify-between text-[11px] text-slate-400">
        <span>Expiry {opt.expiry} · DTE {opt.dte}</span>
        <span>Spread {opt.spread_pct?.toFixed(2)}%</span>
      </div>
      <div className="flex items-center gap-3 mt-1.5 text-[10px] text-slate-400">
        <span>Δ {opt.delta?.toFixed(2)}</span>
        <span>Γ-conv {opt.convexity?.toFixed(3)}</span>
        <span>OI {opt.oi?.toLocaleString('en-IN')}</span>
        <span>Vol {opt.volume?.toLocaleString('en-IN')}</span>
      </div>
    </div>
  );
}

const ALERT_STATUS_COLOR = {
  ACTIVE: 'text-blue-400 bg-blue-500/10', TARGET_1_HIT: 'text-emerald-400 bg-emerald-500/10',
  TARGET_1_HIT_TRAILED: 'text-emerald-400 bg-emerald-500/10', TARGET_2_HIT: 'text-emerald-400 bg-emerald-500/10',
  STOPPED_OUT: 'text-rose-400 bg-rose-500/10',
};

function AlertRow({ alert }) {
  return (
    <div className="rounded-lg bg-slate-900/40 border border-slate-700/40 p-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm font-bold text-white">{alert.contract}</span>
        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${ALERT_STATUS_COLOR[alert.status] || 'text-slate-400 bg-slate-500/10'}`}>
          {alert.status?.replace(/_/g, ' ')}
        </span>
      </div>
      <div className="flex items-center gap-3 text-[11px] text-slate-400">
        <span>Entry ₹{alert.entry_price?.toFixed(2)}</span>
        <span>SL ₹{alert.stop_loss?.toFixed(2)}</span>
        <span>T1 ₹{alert.target_1?.toFixed(2)}</span>
        <span>T2 ₹{alert.target_2?.toFixed(2)}</span>
      </div>
      <div className="text-[10px] text-slate-500 mt-1">{alert.timestamp_ist}</div>
    </div>
  );
}

function WarmingUpSection({ title, note }) {
  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
      {/* Sep 30 2026 fix: real, confirmed bug found via an actual
          mobile-width render (375px) -- items-center vertically
          centers the badge against a title that wraps to 2 lines on
          narrow screens, causing visual overlap. items-start + flex-
          wrap + min-w-0 on the title lets it wrap freely without
          colliding with its sibling, at any width. */}
      <div className="flex items-start justify-between gap-2 flex-wrap mb-2">
        <h3 className="text-sm font-bold text-white min-w-0">{title}</h3>
        <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded text-amber-400 bg-amber-500/10 shrink-0">WARMING UP</span>
      </div>
      <p className="text-xs text-slate-500 italic">{note}</p>
    </div>
  );
}

export default function GammaStrategy() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [exportState, setExportState] = useState({ loading: false, error: null });
  const [historyDates, setHistoryDates] = useState([]);
  const [selectedHistoryDate, setSelectedHistoryDate] = useState('');
  const [historyRows, setHistoryRows] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState(null);

  useEffect(() => {
    fetch(API_BASE + '/api/gamma-strategy/history/dates/')
      .then(res => res.ok ? res.json() : { dates: [] })
      .then(json => setHistoryDates(json.dates || []))
      .catch(() => setHistoryDates([]));
  }, []);

  useEffect(() => {
    if (!selectedHistoryDate) {
      setHistoryRows([]); setHistoryError(null); return;
    }
    let mounted = true;
    setHistoryLoading(true); setHistoryError(null);
    fetch(API_BASE + '/api/gamma-strategy/history/?date=' + encodeURIComponent(selectedHistoryDate))
      .then(res => { if (!res.ok) throw new Error('HTTP ' + res.status); return res.json(); })
      .then(json => { if (mounted) setHistoryRows(json.signals || []); })
      .catch(err => { if (mounted) setHistoryError(err.message); })
      .finally(() => { if (mounted) setHistoryLoading(false); });
    return () => { mounted = false; };
  }, [selectedHistoryDate]);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/gamma-strategy/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (mounted) { setData(json); setError(null); }
      } catch (e) {
        if (mounted) setError(e.message);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    load();
    const interval = setInterval(load, 20000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (loading) {
    return <div className="h-40 rounded-xl bg-slate-900/30 animate-pulse" />;
  }
  if (error || !data) {
    return (
      <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
        <p className="text-sm text-slate-500">{error || 'No data available right now.'}</p>
      </div>
    );
  }

  // Sep 30 2026: same fix as SignalList.jsx's export button -- a plain
  // <a href=... download> would silently force-download a JSON error
  // body with no explanation if the export ever failed (network issue,
  // server down mid-request). This endpoint currently always returns
  // 200 even with empty sheets, so it's less likely to hit this in
  // practice, but the same graceful handling is applied for
  // consistency and to cover a genuine network failure.
  const handleExport = async () => {
    setExportState({ loading: true, error: null });
    try {
      const res = await fetch(`${API_BASE}/api/gamma-strategy/export/`);
      if (!res.ok) {
        let message = `Export failed (HTTP ${res.status}).`;
        try {
          const body = await res.json();
          if (body.error) message = body.error;
        } catch (e) { /* not JSON -- keep the generic HTTP message */ }
        setExportState({ loading: false, error: message });
        return;
      }
      const blob = await res.blob();
      const disposition = res.headers.get('Content-Disposition') || '';
      const match = disposition.match(/filename="?([^"]+)"?/);
      const filename = match ? match[1] : 'gamma_strategy.xlsx';
      const blobUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(blobUrl);
      setExportState({ loading: false, error: null });
    } catch (e) {
      setExportState({ loading: false, error: 'Could not reach the export service.' });
    }
  };

  const resWatch = data.resistance_watchlist || [];
  const supWatch = data.support_watchlist || [];
  const options = data.active_options || { status: 'WARMING_UP', items: [] };
  const alerts = data.microstructure_alerts || { status: 'WARMING_UP', items: [] };
  const ceOptions = (options.items || []).filter((o) => o.option_type === 'CE');
  const peOptions = (options.items || []).filter((o) => o.option_type === 'PE');

  return (
    <div className="space-y-3">
      <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
        {/* Sep 30 2026: same fix applied preventatively -- this header
            happened to avoid visible overlap in the mobile test only
            because the subtitle's own 3-line wrap height absorbed the
            sibling's vertical centering; that's fragile, not a real
            fix, so the same robust pattern is applied here too. */}
        <div className="flex items-start justify-between gap-2 flex-wrap">
          <div className="min-w-0">
            <h2 className="text-base font-bold text-white">Gamma Blast Strategy</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Volatility Supply &amp; Demand zones + 50 EMA macro gate, scanning {data.universe_size} F&amp;O stocks
              {data.symbols_with_zones_today ? ` (${data.symbols_with_zones_today} zone-warmed today)` : ''}
            </p>
          </div>
          {data.updated_at && (
            <span className="text-[10px] text-slate-500 shrink-0">
              Updated {new Date(data.updated_at).toLocaleTimeString('en-IN')}
            </span>
          )}
          {historyDates.length > 0 && (
            <select
              value={selectedHistoryDate}
              onChange={(e) => setSelectedHistoryDate(e.target.value)}
              title="View Gamma Strategy history by date"
              className="h-9 text-xs bg-slate-800 border border-slate-700 rounded-lg px-2 text-slate-300 focus:outline-none focus:border-emerald-500"
            >
              <option value="">Today</option>
              {historyDates.filter(d => d !== new Date().toISOString().slice(0, 10)).map(d => (
                <option key={d} value={d}>
                  {new Date(d + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
                </option>
              ))}
            </select>
          )}
          <button
            onClick={handleExport}
            disabled={exportState.loading}
            title="Download Excel"
            aria-label="Download Excel"
            className="w-9 h-9 shrink-0 flex items-center justify-center rounded-lg text-emerald-400 bg-emerald-500/10 border border-emerald-500/25 hover:bg-emerald-500/20 transition-colors ml-3 disabled:opacity-50"
          >
            {exportState.loading
              ? <div className="w-3.5 h-3.5 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin" />
              : <IconDownload size={16} />}
          </button>
        </div>
        {exportState.error && (
          <p className="text-[11px] text-amber-400 mt-2">{exportState.error}</p>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
          <h3 className="text-sm font-bold text-white mb-3">Resistance Watchlist — CE Candidates</h3>
          {resWatch.length === 0 ? (
            <p className="text-xs text-slate-500 italic">No stocks currently approaching a resistance zone with the 50 EMA gate aligned.</p>
          ) : (
            <div className="space-y-2">
              {resWatch.map((s) => <StockRow key={s.symbol} stock={s} side="resistance" />)}
            </div>
          )}
        </div>

        <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
          <h3 className="text-sm font-bold text-white mb-3">Support Watchlist — PE Candidates</h3>
          {supWatch.length === 0 ? (
            <p className="text-xs text-slate-500 italic">No stocks currently approaching a support zone with the 50 EMA gate aligned.</p>
          ) : (
            <div className="space-y-2">
              {supWatch.map((s) => <StockRow key={s.symbol} stock={s} side="support" />)}
            </div>
          )}
        </div>
      </div>

      {options.status === 'LIVE' ? (
        <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
          {/* Sep 30 2026 fix: same real overlap bug, same fix -- see
              WarmingUpSection's note above for the confirmed cause. */}
          <div className="flex items-start justify-between gap-2 flex-wrap mb-3">
            <h3 className="text-sm font-bold text-white min-w-0">Options Resolver — {options.items.length}-Contract OTM Watchlist</h3>
            {options.updated_at && <span className="text-[10px] text-slate-500 shrink-0">Updated {new Date(options.updated_at).toLocaleTimeString('en-IN')}</span>}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div>
              <p className="text-xs font-semibold text-emerald-400 mb-2">CE Contracts</p>
              <div className="space-y-2">
                {ceOptions.length ? ceOptions.map((o) => <OptionRow key={o.security_id} opt={o} />) : <p className="text-xs text-slate-500 italic">None resolved this cycle.</p>}
              </div>
            </div>
            <div>
              <p className="text-xs font-semibold text-rose-400 mb-2">PE Contracts</p>
              <div className="space-y-2">
                {peOptions.length ? peOptions.map((o) => <OptionRow key={o.security_id} opt={o} />) : <p className="text-xs text-slate-500 italic">None resolved this cycle.</p>}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <WarmingUpSection
          title="Options Resolver — 12-Contract OTM Watchlist"
          note="DTE≥8, delta 0.20–0.45, gamma convexity≥0.150 ranking against live option-chain Greeks. Wired and running — waiting for the first resolution cycle against the watchlist above (paced ~75s per stock to stay clear of Fyers rate limits)."
        />
      )}

      {alerts.status === 'LIVE' ? (
        <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
          <h3 className="text-sm font-bold text-white mb-3">Microstructure Alerts — 4-Phase Trigger</h3>
          <div className="space-y-2">
            {alerts.items.slice().reverse().map((a) => <AlertRow key={a.alert_id} alert={a} />)}
          </div>
        </div>
      ) : (
        <WarmingUpSection
          title="Microstructure Alerts — 4-Phase Trigger"
          note="OI dip → inflection → volume expansion → price lift confluence, per contract. Wired and running — no real 4-phase confluence has fired yet on the current watchlist. This is expected most cycles; the trigger is meant to be rare."
        />
      )}
      {selectedHistoryDate && (
        <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
          <div className="flex items-start justify-between gap-2 flex-wrap mb-3">
            <h3 className="text-sm font-bold text-white min-w-0">
              Gamma Strategy History — {new Date(selectedHistoryDate + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}
            </h3>
            {!historyLoading && !historyError && <span className="text-[10px] text-slate-500 shrink-0">{historyRows.length} signals</span>}
          </div>
          {historyLoading ? (
            <p className="text-xs text-slate-500 italic">Loading historical Gamma signals…</p>
          ) : historyError ? (
            <p className="text-xs text-rose-400">History failed: {historyError}</p>
          ) : historyRows.length === 0 ? (
            <p className="text-xs text-slate-500 italic">No Gamma signals recorded for this date.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-slate-700/50">
              <table className="w-full text-xs">
                <thead className="bg-slate-900/70"><tr>
                  {['Stock','Type','Strike','Entry','Entry Time','SL','T1','T2','Status','Exit'].map(h => <th key={h} className="text-left px-3 py-2 text-slate-400 font-semibold">{h}</th>)}
                </tr></thead>
                <tbody>
                  {historyRows.map((row, idx) => (
                    <tr key={row.contract + '-' + idx} className="border-t border-slate-700/40">
                      <td className="px-3 py-2 text-white font-semibold">{row.symbol || '—'}</td>
                      <td className={row.option_type === 'CE' ? 'px-3 py-2 font-semibold text-emerald-400' : 'px-3 py-2 font-semibold text-rose-400'}>{row.option_type || '—'}</td>
                      <td className="px-3 py-2 text-slate-300">{row.strike ?? '—'}</td>
                      <td className="px-3 py-2 text-slate-300">₹{row.entry_price ?? '—'}</td>
                      <td className="px-3 py-2 text-slate-400 whitespace-nowrap">{row.entry_time_ist || '—'}</td>
                      <td className="px-3 py-2 text-slate-300">₹{row.stop_loss ?? '—'}</td>
                      <td className="px-3 py-2 text-slate-300">₹{row.target_1 ?? '—'}</td>
                      <td className="px-3 py-2 text-slate-300">₹{row.target_2 ?? '—'}</td>
                      <td className="px-3 py-2 text-slate-300">{row.status?.replace(/_/g, ' ') || '—'}</td>
                      <td className="px-3 py-2 text-slate-400 whitespace-nowrap">{row.exit_time_ist || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

