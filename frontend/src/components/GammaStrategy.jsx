import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Sep 23 2026: Gamma Blast Strategy tab -- separate block, direct
// request, own sidebar entry (not folded into Sniper Signals).
//
// Backend status as of this build: resistance_watchlist/support_watchlist
// are REAL and LIVE (zone engine + 50 EMA gate, verified against the
// purchased package's own code before being wired in -- see
// gamma_zone_engine.py/gamma_watchlist_scanner.py). active_options and
// microstructure_alerts are honestly reported as PENDING by the
// backend, not silently empty -- the options resolver (needs this
// project's live Fyers option-chain fetch, not yet wired) and the
// microstructure daemon (needs a continuous tick feed, same reason)
// are still to come. This component renders that PENDING state
// plainly rather than showing an empty list that looks like "ran and
// found nothing."

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

function PendingSection({ title, note }) {
  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-bold text-white">{title}</h3>
        <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded text-amber-400 bg-amber-500/10">PENDING</span>
      </div>
      <p className="text-xs text-slate-500 italic">{note}</p>
    </div>
  );
}

export default function GammaStrategy() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

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

  const resWatch = data.resistance_watchlist || [];
  const supWatch = data.support_watchlist || [];

  return (
    <div className="space-y-3">
      <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-white">Gamma Blast Strategy</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Volatility Supply &amp; Demand zones + 50 EMA macro gate, scanning {data.universe_size} F&amp;O stocks
              {data.symbols_with_zones_today ? ` (${data.symbols_with_zones_today} zone-warmed today)` : ''}
            </p>
          </div>
          {data.updated_at && (
            <span className="text-[10px] text-slate-500">
              Updated {new Date(data.updated_at).toLocaleTimeString('en-IN')}
            </span>
          )}
        </div>
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

      <PendingSection
        title="Options Resolver — 12-Contract OTM Watchlist"
        note="DTE≥8, delta 0.20–0.45, gamma convexity≥0.150 ranking against live option-chain Greeks. Logic ported and tested; not yet wired to this project's live Fyers option-chain fetch."
      />
      <PendingSection
        title="Microstructure Alerts — 4-Phase Trigger"
        note="OI dip → inflection → volume expansion → price lift confluence, per contract. Logic ported and tested; needs a continuous tick feed from the options above before it can run live."
      />
    </div>
  );
}
