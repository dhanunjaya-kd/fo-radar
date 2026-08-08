import { useEffect } from 'react';

const GRADE_STYLES = {
  'A+': { ring: 'ring-emerald-400', bg: 'bg-emerald-500', text: 'text-emerald-400' },
  'A': { ring: 'ring-emerald-500', bg: 'bg-emerald-600', text: 'text-emerald-400' },
  'B': { ring: 'ring-lime-500', bg: 'bg-lime-600', text: 'text-lime-400' },
  'C': { ring: 'ring-amber-500', bg: 'bg-amber-600', text: 'text-amber-400' },
  'D': { ring: 'ring-rose-500', bg: 'bg-rose-600', text: 'text-rose-400' },
};

export default function OptionsDive({ signal, onClose }) {
  if (!signal) return null;

  const fmt = (n) => (n == null || isNaN(n)) ? '—' : n.toLocaleString('en-IN', { maximumFractionDigits: 2 });
  const fmtInt = (n) => (n == null || isNaN(n)) ? '—' : Math.round(n).toLocaleString('en-IN');
  const fmtLakh = (n) => {
    if (n == null || isNaN(n)) return '—';
    const lakhs = n / 100000;
    return `${lakhs >= 0 ? '+' : ''}${lakhs.toFixed(1)}L`;
  };
  const isBuy = signal.action === 'BUY';
  const optSide = isBuy ? 'CE' : 'PE';
  const isUp = (signal.change_percent || 0) >= 0;
  const grade = GRADE_STYLES[signal.grade] || GRADE_STYLES['C'];
  const hasLiveOi = !!signal.live_oi;

  // Real interpretation text, derived from actual fields -- never a
  // canned line unrelated to what this specific stock's numbers show.
  const ceLabel = signal.ce_oi_chg > 0 ? 'CE WRITING (bearish)' : signal.ce_oi_chg < 0 ? 'CE unwinding (bullish)' : '≈ flat';
  const peLabel = signal.pe_oi_chg > 0 ? 'PE WRITING (bullish)' : signal.pe_oi_chg < 0 ? 'PE unwinding (bearish)' : '≈ flat';
  const pcrLabel = signal.pcr == null ? '—' : signal.pcr >= 1 ? 'puts dominant' : 'calls dominant';
  const ivLabel = signal.iv == null ? '—' : signal.iv >= 35 ? 'HIGH vol' : signal.iv <= 18 ? 'LOW vol' : 'moderate vol';

  const insights = [];
  if (hasLiveOi) {
    if (signal.oi_confirmation === 'CONFIRMED') {
      insights.push(`✓ Options positioning confirms the ${signal.action} setup — real OI backs this direction`);
    } else if (signal.oi_confirmation === 'CONFLICT') {
      insights.push(`⚠ Options positioning conflicts with the ${signal.action} setup — ${isBuy ? 'resistance' : 'support'} is building against it`);
    }
    if (signal.pattern === 'Range-Pinned') {
      insights.push(`Spot is pinned within 1.5% of Max Pain — expect chop into expiry rather than a clean trend`);
    }
  }

  useEffect(() => {
    const handleEsc = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto shadow-2xl" onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="flex items-start justify-between p-5 pb-0">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-2xl font-black text-white tracking-tight">{signal.symbol}</h2>
              <span className="text-lg font-bold text-white">₹{fmt(signal.price || signal.entry)}</span>
              <span className={`flex items-center gap-0.5 text-sm font-semibold ${isUp ? 'text-emerald-400' : 'text-rose-400'}`}>
                {isUp ? '▲' : '▼'} {Math.abs(signal.change_percent || 0).toFixed(2)}%
              </span>
            </div>
            <div className="flex items-center gap-2 mt-2 flex-wrap">
              <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${signal.oi_confirmation === 'CONFLICT' ? 'bg-rose-500/15 text-rose-400' : 'bg-emerald-500/15 text-emerald-400'}`}>
                {signal.confidence} confidence
              </span>
              <span className="text-xs text-slate-400 bg-slate-800 px-2.5 py-1 rounded-full">{signal.sector}</span>
            </div>
          </div>
          <div className="flex flex-col items-center gap-1">
            <div className={`w-14 h-14 rounded-full ${grade.bg} ring-4 ${grade.ring}/30 flex flex-col items-center justify-center shadow-lg`}>
              <span className="text-white font-black text-base leading-none">{signal.confidence?.replace('%', '')}</span>
            </div>
            <span className={`text-[10px] font-bold ${grade.text}`}>{signal.grade}-GRADE</span>
          </div>
        </div>

        {signal.pattern && (
          <div className="px-5 pt-3">
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-300 bg-indigo-500/10 border border-indigo-500/25 px-3 py-1.5 rounded-lg">
              📊 {signal.pattern}
            </span>
          </div>
        )}

        <div className="p-5 space-y-4">
          {!hasLiveOi && (
            <div className="bg-amber-500/10 border border-amber-500/25 rounded-xl p-3 text-xs text-amber-300">
              ⚠ No live option chain for this stock right now (Fyers not reachable, or market closed). Levels below are
              price-action based, not real OI — grade is technical-only for this cycle.
            </div>
          )}

          {/* OI CHG row */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-slate-800/50 rounded-xl p-3 border border-slate-700/40">
              <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">CE OI CHG</p>
              <p className={`text-lg font-bold flex items-center gap-1 ${(signal.ce_oi_chg || 0) >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                {(signal.ce_oi_chg || 0) >= 0 ? '↑' : '↓'} {fmtLakh(signal.ce_oi_chg)}
              </p>
              <p className="text-[11px] text-slate-500 mt-0.5">{ceLabel}</p>
            </div>
            <div className="bg-slate-800/50 rounded-xl p-3 border border-slate-700/40">
              <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">PE OI CHG</p>
              <p className={`text-lg font-bold flex items-center gap-1 ${(signal.pe_oi_chg || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {(signal.pe_oi_chg || 0) >= 0 ? '↑' : '↓'} {fmtLakh(signal.pe_oi_chg)}
              </p>
              <p className="text-[11px] text-slate-500 mt-0.5">{peLabel}</p>
            </div>
          </div>

          {/* Max Pain / PCR / IV row */}
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="bg-slate-800/30 rounded-xl p-3 border border-slate-700/30">
              <p className="text-[10px] text-slate-500 uppercase">Max Pain</p>
              <p className="text-base font-bold text-white">₹{fmtInt(signal.max_pain)}</p>
              <p className="text-[10px] text-slate-500 mt-0.5">
                {signal.max_pain_dist_pct != null ? `MP dist ${signal.max_pain_dist_pct > 0 ? '+' : ''}${signal.max_pain_dist_pct}%` : '—'}
              </p>
            </div>
            <div className="bg-slate-800/30 rounded-xl p-3 border border-slate-700/30">
              <p className="text-[10px] text-slate-500 uppercase">PCR</p>
              <p className="text-base font-bold text-indigo-400">{signal.pcr != null ? signal.pcr.toFixed(2) : '—'}</p>
              <p className="text-[10px] text-slate-500 mt-0.5">{pcrLabel}</p>
            </div>
            <div className="bg-slate-800/30 rounded-xl p-3 border border-slate-700/30">
              <p className="text-[10px] text-slate-500 uppercase">IV</p>
              <p className="text-base font-bold text-amber-400">{signal.iv != null ? `${signal.iv.toFixed(1)}%` : '—'}</p>
              <p className="text-[10px] text-slate-500 mt-0.5">{ivLabel}</p>
            </div>
          </div>

          {/* Support / Resistance */}
          <div className="flex gap-3">
            <div className="flex-1 bg-rose-500/10 border border-rose-500/20 rounded-xl py-2 text-center">
              <p className="text-xs text-rose-400 font-semibold">📌 Resistance ₹{fmtInt(signal.resistance)}</p>
            </div>
            <div className="flex-1 bg-emerald-500/10 border border-emerald-500/20 rounded-xl py-2 text-center">
              <p className="text-xs text-emerald-400 font-semibold">🛡 Support ₹{fmtInt(signal.support)}</p>
            </div>
          </div>

          {/* Insight lines */}
          {insights.length > 0 && (
            <div className="space-y-1.5">
              {insights.map((line, i) => (
                <p key={i} className="text-xs text-slate-400 bg-slate-800/40 rounded-lg px-3 py-2">{line}</p>
              ))}
            </div>
          )}

          {/* Trade plan */}
          <div className={`rounded-xl p-4 border ${isBuy ? 'bg-emerald-500/10 border-emerald-500/25' : 'bg-rose-500/10 border-rose-500/25'}`}>
            <p className={`text-center font-bold text-sm mb-3 ${isBuy ? 'text-emerald-400' : 'text-rose-400'}`}>
              {isBuy ? '▲' : '▼'} {signal.action} {optSide} — ₹{fmtInt(signal.strike)} STRIKE
            </p>
            <div className="grid grid-cols-3 gap-3 text-center">
              <div>
                <p className="text-[10px] text-slate-500 uppercase">Entry</p>
                <p className="text-sm font-bold text-white">₹{fmt(signal.entry)}</p>
              </div>
              <div>
                <p className="text-[10px] text-slate-500 uppercase">Stop Loss</p>
                <p className="text-sm font-bold text-rose-400">₹{fmt(signal.sl)}</p>
              </div>
              <div>
                <p className="text-[10px] text-slate-500 uppercase">Target</p>
                <p className="text-sm font-bold text-emerald-400">₹{fmt(signal.target1)}</p>
              </div>
            </div>
            {signal.iv != null && signal.iv >= 35 && (
              <p className="text-[11px] text-amber-400 mt-3 text-center">⚠ High IV — premium can swing hard even if you're right on direction. Buy carefully.</p>
            )}
            <div className="flex justify-between text-[11px] text-slate-500 mt-3 pt-3 border-t border-slate-700/30">
              <span>Qty: {signal.quantity}</span>
              <span className="font-mono">R:R {(signal.risk_reward || 2).toFixed(1)}:1</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
