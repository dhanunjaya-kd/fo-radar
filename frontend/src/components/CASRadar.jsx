import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '/api';

function fmt(n, digits = 2) {
  if (n == null || Number.isNaN(Number(n))) return '—';
  return Number(n).toLocaleString('en-IN', { maximumFractionDigits: digits });
}
function pct(n, digits = 2) {
  if (n == null || Number.isNaN(Number(n))) return '—';
  const v = Number(n);
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`;
}
function tone(n) {
  if (n == null || Number.isNaN(Number(n))) return 'text-slate-500';
  return Number(n) > 0 ? 'text-emerald-400' : Number(n) < 0 ? 'text-rose-400' : 'text-slate-400';
}

function SessionBadge() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  const parts = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).formatToParts(now);
  const h = Number(parts.find(p => p.type === 'hour')?.value || 0);
  const m = Number(parts.find(p => p.type === 'minute')?.value || 0);
  const mins = h * 60 + m;
  const inCas = mins >= 915 && mins < 935;
  const label = inCas ? 'CAS WINDOW' : mins < 915 ? 'PRE-CAS' : 'POST-CAS';
  return <span className={`px-2 py-1 rounded-md border text-[10px] font-semibold tracking-wide ${inCas ? 'text-amber-300 bg-amber-500/10 border-amber-500/30' : 'text-slate-300 bg-slate-800/60 border-slate-700'}`}>{label} · {parts.map(p => p.value).join('')}</span>;
}

function Metric({ label, value, sub, className = 'text-white' }) {
  return <div className="rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-3"><div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div><div className={`mt-1 text-lg font-semibold ${className}`}>{value}</div>{sub && <div className="mt-0.5 text-[10px] text-slate-500">{sub}</div>}</div>;
}

function RateMetric({ label, value, sub }) {
  return <Metric label={label} value={value == null ? '—' : `${fmt(value, 1)}%`} sub={sub} />;
}

export default function CASRadar() {
  const [indexName, setIndexName] = useState('NIFTY');
  const [snapshots, setSnapshots] = useState([]);
  const [moves, setMoves] = useState([]);
  const [research, setResearch] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [updated, setUpdated] = useState(null);

  const loadTracker = async () => {
    try {
      const res = await fetch(`${API_BASE}/index-tracker/${indexName}/`);
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || `Index Tracker HTTP ${res.status}`);
      setSnapshots(data.snapshots || []);
      setError(null);
      setUpdated(new Date());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const loadHistory = async () => {
    try {
      const res = await fetch(`${API_BASE}/cas-auction-moves/${indexName}/`);
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || `CAS HTTP ${res.status}`);
      setMoves(data.moves || []);
    } catch (e) {
      setError(e.message);
    }
  };

  const loadResearch = async () => {
    try {
      const res = await fetch(`${API_BASE}/cas-research/${indexName}/?threshold=0.25`);
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || `CAS research HTTP ${res.status}`);
      setResearch(data);
    } catch (e) {
      setResearch(null);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const runTracker = () => { if (!cancelled) loadTracker(); };
    const runHistory = () => { if (!cancelled) loadHistory(); };
    const runResearch = () => { if (!cancelled) loadResearch(); };
    runTracker();
    runHistory();
    runResearch();
    const trackerId = setInterval(runTracker, 15000);
    const historyId = setInterval(runHistory, 60000);
    const researchId = setInterval(runResearch, 60000);
    return () => { cancelled = true; clearInterval(trackerId); clearInterval(historyId); clearInterval(researchId); };
  }, [indexName]);

  const latest = snapshots[0];
  const latestMove = moves[0];
  const summary = research?.summary;
  const momentumMetric = summary?.simple_threshold_metrics?.find(m => m.feature === 'momentum_pct');
  const conservative = summary?.conservative_validation;
  const lead = summary?.lead_time_profile || [];
  const readiness = summary?.status === 'research_sample' ? 'Research sample available' : 'Collecting sample';

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div><h2 className="text-lg font-semibold text-white">CAS Radar</h2><p className="text-xs text-slate-500 mt-0.5">Closing Auction Session · observation and validation layer</p></div>
        <div className="flex items-center gap-2"><SessionBadge /><select value={indexName} onChange={e => setIndexName(e.target.value)} className="bg-slate-900 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-200"><option value="NIFTY">NIFTY</option><option value="BANKNIFTY">BANKNIFTY</option></select></div>
      </div>

      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3">
        <div className="text-xs font-semibold text-amber-300">Research mode · no fabricated auction fields</div>
        <div className="mt-1 text-[11px] leading-5 text-slate-400">The existing project data is Fyers-backed. Standard stored snapshots do not contain CAS IEP, indicative quantity or buy/sell imbalance, so this screen never invents those values. The research layer measures the observable underlying/options reaction first.</div>
      </div>

      {loading && !latest ? <div className="py-12 text-center text-xs text-slate-500">Loading CAS data…</div> : error ? <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-4 text-xs text-rose-300">{error}</div> : <>
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-2">
          <Metric label="Latest Spot" value={fmt(latest?.Spot)} sub={latest?.Time || 'No snapshot'} />
          <Metric label="Day Change" value={pct(latest?.['Change %'], 2)} className={tone(latest?.['Change %'])} />
          <Metric label="Pre→Post CAS" value={pct(latestMove?.move_pct)} className={tone(latestMove?.move_pct)} sub={latestMove?.date || 'No complete session'} />
          <Metric label="PCR" value={fmt(latest?.PCR)} />
          <Metric label="IV" value={latest?.['IV %'] != null ? `${fmt(latest['IV %'], 1)}%` : '—'} />
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div><div className="font-semibold text-white text-sm">CAS Early-Warning Research</div><div className="text-[10px] text-slate-500 mt-0.5">Features are read at 15:16–15:18; outcomes are measured only afterwards. No look-ahead feature is used.</div></div>
            <span className="text-[10px] px-2 py-1 rounded-md border border-slate-700 text-slate-400">{readiness}</span>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-6 gap-2 mt-3">
            <Metric label="Valid events" value={fmt(summary?.sample_size, 0)} />
            <RateMetric label="Large move rate" value={summary?.large_move_rate_pct} sub="≥ 0.25% in 5m" />
            <RateMetric label="Expiry candidate" value={summary?.expiry_candidate_large_move_rate_pct} sub={summary ? `${summary.expiry_candidate_sample} events` : 'Weekday proxy'} />
            <RateMetric label="Non-expiry" value={summary?.non_expiry_large_move_rate_pct} sub={summary ? `${summary.non_expiry_sample} events` : '—'} />
            <Metric label="Momentum precision" value={momentumMetric?.precision_pct != null ? `${fmt(momentumMetric.precision_pct, 1)}%` : '—'} sub={momentumMetric ? `≥0.05% · n=${momentumMetric.sample_size}` : 'Not enough data'} />
            <Metric label="Day-level precision" value={conservative?.precision_pct != null ? `${fmt(conservative.precision_pct, 1)}%` : '—'} sub={conservative ? `earliest/day · n=${conservative.sample_size_days}` : 'Not enough data'} />
          </div>
          <div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/40 p-3">
            <div className="text-[10px] uppercase tracking-wide text-slate-600">Lead-time profile · 5-minute-separated observations</div>
            <div className="grid grid-cols-4 gap-2 mt-2">
              {lead.map(item => <div key={item.horizon_minutes} className="text-center"><div className="text-sm font-semibold text-slate-200">{item.large_move_rate_pct == null ? '—' : `${fmt(item.large_move_rate_pct, 1)}%`}</div><div className="text-[10px] text-slate-600">{item.horizon_minutes}m · n={item.sample_size}</div></div>)}
            </div>
          </div>
          <div className="mt-3 text-[10px] leading-5 text-slate-500">These are diagnostics, not a trading edge. Same-day observations are correlated; expiry is currently a weekday candidate; no probability or BUY/SELL rule is produced.</div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between"><div><div className="font-semibold text-white text-sm">CAS Outcome History</div><div className="text-[10px] text-slate-500">Last snapshot before 15:15 → first reliable snapshot after 15:35</div></div><div className="text-[10px] text-slate-600">Updated {updated ? updated.toLocaleTimeString('en-IN', { hour12: false }) : '—'}</div></div>
          <div className="overflow-x-auto"><table className="w-full text-xs"><thead><tr className="bg-slate-800/50 text-[10px] uppercase text-slate-500"><th className="text-left px-3 py-2">Date</th><th className="text-left px-3 py-2">Pre</th><th className="text-right px-3 py-2">Pre Price</th><th className="text-left px-3 py-2">Post</th><th className="text-right px-3 py-2">Post Price</th><th className="text-right px-3 py-2">Move</th><th className="text-right px-3 py-2">Move %</th></tr></thead><tbody>
            {moves.slice(0, 20).map((r, i) => <tr key={r.date || i} className="border-t border-slate-800/50 hover:bg-slate-800/20"><td className="px-3 py-2 font-mono text-slate-400">{r.date}</td><td className="px-3 py-2 text-slate-500">{r.pre_auction_time}</td><td className="px-3 py-2 text-right text-slate-300">{fmt(r.pre_auction_price)}</td><td className="px-3 py-2 text-slate-500">{r.post_auction_time}</td><td className="px-3 py-2 text-right text-slate-300">{fmt(r.post_auction_price)}</td><td className={`px-3 py-2 text-right font-medium ${tone(r.move_abs)}`}>{fmt(r.move_abs)}</td><td className={`px-3 py-2 text-right font-medium ${tone(r.move_pct)}`}>{pct(r.move_pct)}</td></tr>)}
            {!moves.length && <tr><td colSpan="7" className="px-3 py-8 text-center text-slate-600">No complete CAS sessions in the logged dataset yet.</td></tr>}
          </tbody></table></div>
        </div>

        <div className="grid lg:grid-cols-2 gap-3">
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4"><div className="text-sm font-semibold text-white">Current research protocol</div><ul className="mt-2 space-y-1.5 text-[11px] text-slate-500 leading-5 list-disc pl-4"><li>Use only 15:16–15:18 information for early-warning features.</li><li>Measure actual forward movement at 1, 2, 3 and 5 minutes.</li><li>Use 5-minute-separated observations and earliest-event-per-day validation.</li><li>Compare expiry candidates with non-expiry controls before fitting anything.</li></ul></div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4"><div className="text-sm font-semibold text-white">Hard safety boundaries</div><ul className="mt-2 space-y-1.5 text-[11px] text-slate-500 leading-5 list-disc pl-4"><li>No 3:19 PM fixed-time rule.</li><li>No BUY/SELL rule from PCR, OI or Bias alone.</li><li>No IEP/imbalance values unless a verified feed supplies them.</li><li>No probability score until an out-of-sample time-series test supports calibration.</li></ul></div>
        </div>
      </>}
    </div>
  );
}
