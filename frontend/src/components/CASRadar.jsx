import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '/api';

function fmt(n, digits = 2) {
  if (n == null || Number.isNaN(Number(n))) return '—';
  return Number(n).toLocaleString('en-IN', { maximumFractionDigits: digits });
}
function pct(n, digits = 3) {
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
  const mins = now.getHours() * 60 + now.getMinutes();
  const inCas = mins >= 915 && mins < 935;
  const label = inCas ? 'CAS WINDOW' : mins < 915 ? 'PRE-CAS' : 'POST-CAS';
  return <span className={`px-2 py-1 rounded-md border text-[10px] font-semibold tracking-wide ${inCas ? 'text-amber-300 bg-amber-500/10 border-amber-500/30' : 'text-slate-300 bg-slate-800/60 border-slate-700'}`}>{label} · {now.toLocaleTimeString('en-IN', { hour12: false })}</span>;
}

function Metric({ label, value, sub, className = 'text-white' }) {
  return <div className="rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-3"><div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div><div className={`mt-1 text-lg font-semibold ${className}`}>{value}</div>{sub && <div className="mt-0.5 text-[10px] text-slate-500">{sub}</div>}</div>;
}

export default function CASRadar() {
  const [indexName, setIndexName] = useState('NIFTY');
  const [snapshots, setSnapshots] = useState([]);
  const [moves, setMoves] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [updated, setUpdated] = useState(null);

  const load = async () => {
    try {
      const [trackerRes, casRes] = await Promise.all([
        fetch(`${API_BASE}/index-tracker/${indexName}/`),
        fetch(`${API_BASE}/cas-auction-moves/${indexName}/`),
      ]);
      const [tracker, cas] = await Promise.all([trackerRes.json(), casRes.json()]);
      if (!trackerRes.ok || tracker.error) throw new Error(tracker.error || `Index Tracker HTTP ${trackerRes.status}`);
      if (!casRes.ok || cas.error) throw new Error(cas.error || `CAS HTTP ${casRes.status}`);
      setSnapshots(tracker.snapshots || []);
      setMoves(cas.moves || []);
      setError(null);
      setUpdated(new Date());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const run = () => { if (!cancelled) load(); };
    run();
    const id = setInterval(run, 15000);
    return () => { cancelled = true; clearInterval(id); };
  }, [indexName]);

  const latest = snapshots[0];
  const latestMove = moves[0];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div><h2 className="text-lg font-semibold text-white">CAS Radar</h2><p className="text-xs text-slate-500 mt-0.5">Closing Auction Session · observation and validation layer</p></div>
        <div className="flex items-center gap-2"><SessionBadge /><select value={indexName} onChange={e => setIndexName(e.target.value)} className="bg-slate-900 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-200"><option value="NIFTY">NIFTY</option><option value="BANKNIFTY">BANKNIFTY</option></select></div>
      </div>

      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3">
        <div className="text-xs font-semibold text-amber-300">Important data boundary</div>
        <div className="mt-1 text-[11px] leading-5 text-slate-400">The existing project data is Fyers-backed. Standard stored snapshots do not contain CAS IEP, indicative quantity or buy/sell imbalance, so this screen never invents those values. We first measure the observable underlying/options reaction; a real auction-feed provider can be added later without changing the research definition.</div>
      </div>

      {loading && !latest ? <div className="py-12 text-center text-xs text-slate-500">Loading CAS data…</div> : error ? <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-4 text-xs text-rose-300">{error}</div> : <>
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-2">
          <Metric label="Latest Spot" value={fmt(latest?.Spot)} sub={latest?.Time || 'No snapshot'} />
          <Metric label="Day Change" value={pct(latest?.['Change %'], 2)} className={tone(latest?.['Change %'])} />
          <Metric label="Pre→Post CAS" value={pct(latestMove?.move_pct)} className={tone(latestMove?.move_pct)} sub={latestMove?.date || 'No complete session'} />
          <Metric label="PCR" value={fmt(latest?.PCR)} />
          <Metric label="IV" value={latest?.['IV %'] != null ? `${fmt(latest['IV %'], 1)}%` : '—'} />
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between"><div><div className="font-semibold text-white text-sm">CAS Outcome History</div><div className="text-[10px] text-slate-500">Last snapshot before 15:15 → first reliable snapshot after 15:35</div></div><div className="text-[10px] text-slate-600">Updated {updated ? updated.toLocaleTimeString('en-IN', { hour12: false }) : '—'}</div></div>
          <div className="overflow-x-auto"><table className="w-full text-xs"><thead><tr className="bg-slate-800/50 text-[10px] uppercase text-slate-500"><th className="text-left px-3 py-2">Date</th><th className="text-left px-3 py-2">Pre</th><th className="text-right px-3 py-2">Pre Price</th><th className="text-left px-3 py-2">Post</th><th className="text-right px-3 py-2">Post Price</th><th className="text-right px-3 py-2">Move</th><th className="text-right px-3 py-2">Move %</th></tr></thead><tbody>
            {moves.slice(0, 20).map((r, i) => <tr key={r.date || i} className="border-t border-slate-800/50 hover:bg-slate-800/20"><td className="px-3 py-2 font-mono text-slate-400">{r.date}</td><td className="px-3 py-2 text-slate-500">{r.pre_auction_time}</td><td className="px-3 py-2 text-right text-slate-300">{fmt(r.pre_auction_price)}</td><td className="px-3 py-2 text-slate-500">{r.post_auction_time}</td><td className="px-3 py-2 text-right text-slate-300">{fmt(r.post_auction_price)}</td><td className={`px-3 py-2 text-right font-medium ${tone(r.move_abs)}`}>{fmt(r.move_abs)}</td><td className={`px-3 py-2 text-right font-medium ${tone(r.move_pct)}`}>{pct(r.move_pct)}</td></tr>)}
            {!moves.length && <tr><td colSpan="7" className="px-3 py-8 text-center text-slate-600">No complete CAS sessions in the logged dataset yet.</td></tr>}
          </tbody></table></div>
        </div>

        <div className="grid lg:grid-cols-2 gap-3">
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4"><div className="text-sm font-semibold text-white">What we can measure now</div><ul className="mt-2 space-y-1.5 text-[11px] text-slate-500 leading-5 list-disc pl-4"><li>Pre-CAS underlying level and options context already logged by Index Tracker.</li><li>Actual post-CAS displacement and its date/time, without pretending the move occurred at a fixed minute.</li><li>Expiry-day versus non-expiry-day outcomes once the historical sample is large enough.</li><li>Lead-time research after we have sufficiently granular observations.</li></ul></div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4"><div className="text-sm font-semibold text-white">Not yet claimed</div><ul className="mt-2 space-y-1.5 text-[11px] text-slate-500 leading-5 list-disc pl-4"><li>No 3:19 PM fixed-time rule.</li><li>No BUY/SELL rule from PCR, OI or Bias alone.</li><li>No IEP/imbalance values unless a verified feed supplies them.</li><li>No probability score until it is fitted and evaluated out-of-sample.</li></ul></div>
        </div>
      </>}
    </div>
  );
}
