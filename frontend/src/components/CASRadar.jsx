import { useEffect, useMemo, useState } from 'react';

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

function statusForMove(n) {
  if (n == null) return 'text-slate-500';
  return Number(n) > 0 ? 'text-emerald-400' : Number(n) < 0 ? 'text-rose-400' : 'text-slate-400';
}

function SessionBadge() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const mins = now.getHours() * 60 + now.getMinutes();
  const inCas = mins >= 15 * 60 + 15 && mins < 15 * 60 + 35;
  const before = mins < 15 * 60 + 15;
  const label = inCas ? 'CAS WINDOW' : before ? 'PRE-CAS' : 'POST-CAS';
  const cls = inCas
    ? 'text-amber-300 bg-amber-500/10 border-amber-500/30'
    : 'text-slate-300 bg-slate-800/60 border-slate-700';

  return (
    <span className={`px-2 py-1 rounded-md border text-[10px] font-semibold tracking-wide ${cls}`}>
      {label} · {now.toLocaleTimeString('en-IN', { hour12: false })}
    </span>
  );
}

function Metric({ label, value, sub, tone = 'text-white' }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${tone}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[10px] text-slate-500">{sub}</div>}
    </div>
  );
}

function IndexPanel({ name, snapshot, history }) {
  const move = history?.[0]?.move_pct;
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
        <div>
          <div className="font-semibold text-white">{name}</div>
          <div className="text-[10px] text-slate-500">CAS research feed · Fyers-backed project data</div>
        </div>
        <div className={`text-sm font-semibold ${statusForMove(move)}`}>{pct(move)}</div>
      </div>
      <div className="p-3 grid grid-cols-2 lg:grid-cols-4 gap-2">
        <Metric label="Spot" value={fmt(snapshot?.Spot)} />
        <Metric label="3:15→post CAS" value={pct(move)} tone={statusForMove(move)} />
        <Metric label="PCR" value={fmt(snapshot?.PCR)} />
        <Metric label="IV" value={snapshot?.['IV %'] != null ? `${fmt(snapshot['IV %'], 1)}%` : '—'} />
      </div>
      <div className="px-3 pb-3 text-[10px] text-slate-500">
        Latest logged snapshot: <span className="font-mono text-slate-400">{snapshot?.Time || '—'}</span>
        {' · '}
        Bias: <span className="text-slate-300">{snapshot?.Bias || '—'}</span>
        {' · '}
        Momentum: <span className={statusForMove(snapshot?.['Momentum %'])}>{pct(snapshot?.['Momentum %'])}</span>
      </div>
    </div>
  );
}

export default function CASRadar() {
  const [indexName, setIndexName] = useState('NIFTY');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  const load = async () => {
    try {
      const res = await fetch(`${API_BASE}/cas-radar/${indexName}/`);
      const json = await res.json();
      if (!res.ok || json.error) throw new Error(json.error || `HTTP ${res.status}`);
      setData(json);
      setError(null);
      setLastUpdated(new Date());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const first = async () => { if (!cancelled) await load(); };
    first();
    const id = setInterval(() => { if (!cancelled) load(); }, 15000);
    return () => { cancelled = true; clearInterval(id); };
  }, [indexName]);

  const recent = useMemo(() => (data?.history || []).slice(0, 10), [data]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold text-white">CAS Radar</h2>
          <p className="text-xs text-slate-500 mt-0.5">Closing Auction Session · research first, no-look-ahead by design</p>
        </div>
        <div className="flex items-center gap-2">
          <SessionBadge />
          <select
            value={indexName}
            onChange={e => setIndexName(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-200"
          >
            <option value="NIFTY">NIFTY</option>
            <option value="BANKNIFTY">BANKNIFTY</option>
          </select>
        </div>
      </div>

      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3">
        <div className="text-xs font-semibold text-amber-300">Data boundary</div>
        <div className="mt-1 text-[11px] leading-5 text-slate-400">
          This screen uses only data the project already receives from Fyers. CAS-specific IEP, indicative quantity and imbalance are not treated as available unless the feed actually supplies them. The current research layer therefore measures the observable price/options reaction and keeps auction microstructure explicitly unavailable instead of fabricating it.
        </div>
      </div>

      {loading && !data ? (
        <div className="py-12 text-center text-xs text-slate-500">Loading CAS research data…</div>
      ) : error ? (
        <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-4 text-xs text-rose-300">{error}</div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
            <Metric label="Latest Spot" value={fmt(data?.latest?.Spot)} sub={data?.latest?.Time || 'No snapshot'} />
            <Metric label="Day Change" value={pct(data?.latest?.['Change %'], 2)} tone={statusForMove(data?.latest?.['Change %'])} />
            <Metric label="CAS Window" value={data?.cas_window ? 'ACTIVE' : 'INACTIVE'} tone={data?.cas_window ? 'text-amber-300' : 'text-slate-300'} sub="15:15–15:35 IST" />
            <Metric label="Microstructure" value="Unavailable" tone="text-slate-400" sub="IEP / imbalance not supplied" />
          </div>

          <IndexPanel name={indexName} snapshot={data?.latest} history={data?.history} />

          <div className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
              <div>
                <div className="font-semibold text-white text-sm">CAS Outcome History</div>
                <div className="text-[10px] text-slate-500">Pre-CAS snapshot → first reliable post-CAS snapshot</div>
              </div>
              <div className="text-[10px] text-slate-600">Updated {lastUpdated ? lastUpdated.toLocaleTimeString('en-IN', { hour12: false }) : '—'}</div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-slate-800/50 text-[10px] uppercase text-slate-500">
                    <th className="text-left px-3 py-2">Date</th>
                    <th className="text-left px-3 py-2">Pre</th>
                    <th className="text-right px-3 py-2">Pre Price</th>
                    <th className="text-left px-3 py-2">Post</th>
                    <th className="text-right px-3 py-2">Post Price</th>
                    <th className="text-right px-3 py-2">Move</th>
                    <th className="text-right px-3 py-2">Move %</th>
                  </tr>
                </thead>
                <tbody>
                  {recent.map(r => (
                    <tr key={r.date} className="border-t border-slate-800/50 hover:bg-slate-800/20">
                      <td className="px-3 py-2 font-mono text-slate-400">{r.date}</td>
                      <td className="px-3 py-2 text-slate-500">{r.pre_auction_time}</td>
                      <td className="px-3 py-2 text-right text-slate-300">{fmt(r.pre_auction_price)}</td>
                      <td className="px-3 py-2 text-slate-500">{r.post_auction_time}</td>
                      <td className="px-3 py-2 text-right text-slate-300">{fmt(r.post_auction_price)}</td>
                      <td className={`px-3 py-2 text-right font-medium ${statusForMove(r.move_abs)}`}>{fmt(r.move_abs)}</td>
                      <td className={`px-3 py-2 text-right font-medium ${statusForMove(r.move_pct)}`}>{pct(r.move_pct)}</td>
                    </tr>
                  ))}
                  {!recent.length && (
                    <tr><td colSpan="7" className="px-3 py-8 text-center text-slate-600">No complete CAS sessions in the logged dataset yet.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/30 p-4">
            <div className="text-xs font-semibold text-slate-300">What this proves — and what it does not</div>
            <ul className="mt-2 space-y-1.5 text-[11px] text-slate-500 leading-5 list-disc pl-4">
              <li>It measures the actual post-CAS price displacement from real logged snapshots.</li>
              <li>It does not claim that a 3:19 move is predictable; the historical timestamps are preserved so lead time can be tested later.</li>
              <li>It does not convert PCR/OI/Bias into a trade signal. Those are context variables, not a validated CAS predictor.</li>
              <li>Once sufficiently granular pre-CAS observations accumulate, this tab can be extended into a measured early-warning study without changing the historical definition.</li>
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
