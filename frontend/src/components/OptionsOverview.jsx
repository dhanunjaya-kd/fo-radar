import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Aug 28 2026: coordinate/range math verified in test_slider_math.js
// before this was written -- confirmed both markers land within the
// readable 15-85% zone (not crowded at the edges) at both NIFTY and
// BANKNIFTY's real price scales, and correctly handle spot on either
// side of max pain plus the spot===maxPain edge case.
function computeSliderRange(spot, maxPain) {
  const lo = Math.min(spot, maxPain);
  const hi = Math.max(spot, maxPain);
  const span = hi - lo;
  const minSpan = spot * 0.005;
  const effectiveSpan = Math.max(span, minSpan);
  const padding = effectiveSpan * 1.5;
  const rangeLo = lo - padding;
  const rangeHi = hi + padding;
  const pct = (val) => ((val - rangeLo) / (rangeHi - rangeLo)) * 100;
  return { rangeLo, rangeHi, spotPct: pct(spot), maxPainPct: pct(maxPain) };
}

function StatCard({ label, value, sub, subTone }) {
  const toneClass = { emerald: 'text-emerald-400', rose: 'text-rose-400', slate: 'text-slate-400', amber: 'text-amber-400' }[subTone] || 'text-slate-400';
  return (
    <div className="bg-slate-900/40 rounded-lg p-3">
      <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1">{label}</p>
      <p className="text-lg font-bold text-white tabular-nums">{value}</p>
      {sub && <p className={`text-[11px] font-medium mt-0.5 ${toneClass}`}>{sub}</p>}
    </div>
  );
}

export default function OptionsOverview() {
  const [selected, setSelected] = useState('NIFTY');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/option-analytics/${selected}/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (mounted) {
          if (json.live === false) {
            setError(json.error || 'No live data available right now.');
            setData(null);
          } else {
            setData(json);
          }
        }
      } catch (err) {
        if (mounted) { console.error('Options overview fetch error:', err); setError(err.message); }
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, [selected]);

  const pcrSentiment = (pcr) => {
    if (pcr == null) return { label: 'N/A', tone: 'slate' };
    if (pcr > 1.05) return { label: 'Bullish', tone: 'emerald' };
    if (pcr < 0.95) return { label: 'Bearish', tone: 'rose' };
    return { label: 'Neutral', tone: 'amber' };
  };

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-white">Options Overview</h3>
        <div className="flex gap-1 bg-slate-900/50 p-0.5 rounded-lg">
          {['NIFTY', 'BANKNIFTY'].map(idx => (
            <button
              key={idx}
              onClick={() => setSelected(idx)}
              className={`text-[11px] font-medium px-2.5 py-1 rounded-md transition-colors ${
                selected === idx ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {idx}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="h-40 rounded-lg bg-slate-900/30 animate-pulse" />
      ) : error || !data ? (
        <div className="py-8 text-center">
          <p className="text-sm text-slate-500">{error || 'No live option chain available right now.'}</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-4">
            <StatCard
              label="PCR (OI)"
              value={data.pcr != null ? data.pcr.toFixed(2) : '—'}
              sub={pcrSentiment(data.pcr).label}
              subTone={pcrSentiment(data.pcr).tone}
            />
            <StatCard
              label="Max Pain"
              value={data.maxPain != null ? data.maxPain.toLocaleString('en-IN') : '—'}
              sub={data.maxPainDistPct != null ? `${data.maxPainDistPct >= 0 ? '+' : ''}${data.maxPainDistPct.toFixed(2)}%` : null}
              subTone={data.maxPainDistPct >= 0 ? 'rose' : 'emerald'}
            />
            <StatCard
              label="ATM IV"
              value={data.atmIv != null ? `${data.atmIv.toFixed(1)}%` : '—'}
              sub="Implied Volatility"
              subTone="slate"
            />
            <StatCard
              label="PCR (Volume)"
              value={data.pcrVolume != null ? data.pcrVolume.toFixed(2) : '—'}
              sub={pcrSentiment(data.pcrVolume).label}
              subTone={pcrSentiment(data.pcrVolume).tone}
            />
          </div>

          {data.spot != null && data.maxPain != null && (() => {
            const range = computeSliderRange(data.spot, data.maxPain);
            return (
              <div className="mb-4">
                <div className="flex items-center justify-between text-[10px] text-slate-500 mb-1.5">
                  <span>Max Pain vs Spot</span>
                </div>
                <div className="relative h-2 bg-slate-900/50 rounded-full">
                  <div
                    className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-blue-400 border-2 border-slate-800 shadow"
                    style={{ left: `${range.spotPct}%`, transform: 'translate(-50%, -50%)' }}
                    title={`Spot: ${data.spot.toLocaleString('en-IN')}`}
                  />
                  <div
                    className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-amber-400 border-2 border-slate-800 shadow"
                    style={{ left: `${range.maxPainPct}%`, transform: 'translate(-50%, -50%)' }}
                    title={`Max Pain: ${data.maxPain.toLocaleString('en-IN')}`}
                  />
                </div>
                <div className="flex items-center justify-between text-[10px] text-slate-500 mt-1.5">
                  <span>{range.rangeLo.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
                  <span className="flex items-center gap-3">
                    <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-blue-400" /> Spot: {data.spot.toLocaleString('en-IN')}</span>
                    <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-amber-400" /> Max Pain: {data.maxPain.toLocaleString('en-IN')}</span>
                  </span>
                  <span>{range.rangeHi.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
                </div>
              </div>
            );
          })()}

          <div className="bg-slate-900/40 rounded-lg p-3 text-center">
            <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1">ATM Straddle</p>
            <p className="text-xl font-bold text-white tabular-nums">
              {data.atmStraddlePrice != null ? `₹${data.atmStraddlePrice.toFixed(2)}` : '—'}
            </p>
            <p className="text-[10px] text-slate-500 mt-0.5">
              {data.atmStrike != null ? `Strike ${data.atmStrike.toLocaleString('en-IN')} — implied expected move by expiry` : ''}
            </p>
          </div>
        </>
      )}
    </div>
  );
}
