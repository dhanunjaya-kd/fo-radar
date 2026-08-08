import { useState } from 'react';
import OptionsDive from './OptionsDive';

// Icon set matches the stroke-based SVG style used across the other tabs
// (Analytics.jsx / SignalList.jsx / Watchlist.jsx) instead of raw emoji --
// currentColor-driven, so they reliably pick up each badge's tone color.
const IconBolt = ({ size = 11 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
);
const IconCheck = ({ size = 11 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
);
const IconAlertTriangle = ({ size = 11 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
);
const IconTriangleUp = ({ size = 12 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="12 4 20 18 4 18"/></svg>
);
const IconTriangleDown = ({ size = 12 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="12 20 4 6 20 6"/></svg>
);
const IconShield = ({ size = 9 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
);
const IconMapPin = ({ size = 9 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
);
const IconSearch = ({ size = 9 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
);

const GRADE_STYLES = {
  'A+': { bg: 'bg-emerald-500', ring: 'ring-emerald-400', text: 'text-emerald-400' },
  'A': { bg: 'bg-emerald-600', ring: 'ring-emerald-500', text: 'text-emerald-400' },
  'B': { bg: 'bg-lime-600', ring: 'ring-lime-500', text: 'text-lime-400' },
  'C': { bg: 'bg-amber-600', ring: 'ring-amber-500', text: 'text-amber-400' },
  'D': { bg: 'bg-rose-600', ring: 'ring-rose-500', text: 'text-rose-400' },
};

export default function SniperCard({ signal }) {
  const [showModal, setShowModal] = useState(false);

  if (!signal) return null;

  const isBuy = signal.action === 'BUY';
  const isPositive = (signal.change_percent || 0) >= 0;
  const grade = GRADE_STYLES[signal.grade] || GRADE_STYLES['C'];

  const fmt = (n) => {
    if (n == null || isNaN(n)) return '—';
    return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  const fmtInt = (n) => {
    if (n == null || isNaN(n)) return '—';
    return Math.round(n).toLocaleString('en-IN');
  };
  const fmtLakh = (n) => {
    if (n == null || isNaN(n)) return '—';
    const lakhs = n / 100000;
    return `${lakhs >= 0 ? '+' : ''}${lakhs.toFixed(1)}L`;
  };

  return (
    <>
      <div
        className="rounded-lg bg-slate-800/50 border border-slate-700/40 p-3.5 hover:border-slate-600/60 hover:bg-slate-800/70 transition-all cursor-pointer group"
        onClick={() => setShowModal(true)}
      >
        {/* Top Row */}
        <div className="flex items-center justify-between mb-2.5">
          <div className="flex items-center gap-1.5">
            <h3 className="text-base font-bold text-white">{signal.symbol}</h3>
            <span className={`text-[11px] px-1.5 py-0.5 rounded ${isPositive ? 'bg-emerald-500/15 text-emerald-400' : 'bg-rose-500/15 text-rose-400'}`}>
              {isPositive ? '+' : ''}{signal.change_percent?.toFixed(2)}%
            </span>
          </div>
          <div className="flex flex-col items-center gap-0.5">
            <div className={`w-9 h-9 rounded-full ${grade.bg} ring-2 ${grade.ring}/40 flex items-center justify-center shadow-lg`}>
              <span className="text-[11px] font-black text-white leading-none">{signal.confidence?.replace('%', '')}</span>
            </div>
            <span className={`text-[8px] font-bold ${grade.text}`}>{signal.grade}</span>
          </div>
        </div>

        {/* Price + Meta */}
        <div className="flex items-center gap-1.5 mb-2.5 text-[11px] flex-wrap">
          <span className="text-white font-semibold text-xs">₹{fmt(signal.price || signal.entry)}</span>
          <span className={`px-1.5 py-0.5 rounded-full ${signal.oi_confirmation === 'CONFLICT' ? 'text-rose-400 bg-rose-500/10' : 'text-emerald-400 bg-emerald-500/10'}`}>
            {signal.confidence} confidence
          </span>
          <span className="text-slate-400 bg-slate-700/30 px-1.5 py-0.5 rounded-full">{signal.sector}</span>
          <span className="text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded-full font-bold inline-flex items-center gap-1">
            <IconBolt size={10} /> SNIPER
          </span>
        </div>

        {/* OI confirmation + pattern */}
        {(signal.oi_confirmation && signal.oi_confirmation !== 'NO_DATA') || signal.pattern ? (
          <div className="flex items-center gap-1.5 mb-2.5 text-[11px] flex-wrap">
            {signal.oi_confirmation === 'CONFIRMED' && (
              <span className="text-emerald-400 bg-emerald-500/10 border border-emerald-500/25 px-1.5 py-0.5 rounded-full font-medium inline-flex items-center gap-1">
                <IconCheck size={10} /> OI Confirmed
              </span>
            )}
            {signal.oi_confirmation === 'CONFLICT' && (
              <span className="text-rose-400 bg-rose-500/10 border border-rose-500/25 px-1.5 py-0.5 rounded-full font-medium inline-flex items-center gap-1">
                <IconAlertTriangle size={10} /> OI Conflict
              </span>
            )}
            {signal.pattern && (
              <span className="text-indigo-300 bg-indigo-500/10 border border-indigo-500/25 px-1.5 py-0.5 rounded-full font-medium">{signal.pattern}</span>
            )}
          </div>
        ) : null}

        {/* OI Grid */}
        <div className="grid grid-cols-3 gap-1.5 mb-2.5">
          <div className="bg-slate-900/40 rounded-md p-1.5 text-center">
            <p className="text-[9px] text-slate-500 uppercase">CE OI</p>
            <p className={`text-xs font-bold ${(signal.ce_oi_chg || 0) >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>{fmtLakh(signal.ce_oi_chg)}</p>
          </div>
          <div className="bg-slate-900/40 rounded-md p-1.5 text-center">
            <p className="text-[9px] text-slate-500 uppercase">PE OI</p>
            <p className={`text-xs font-bold ${(signal.pe_oi_chg || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{fmtLakh(signal.pe_oi_chg)}</p>
          </div>
          <div className="bg-slate-900/40 rounded-md p-1.5 text-center">
            <p className="text-[9px] text-slate-500 uppercase">IV</p>
            <p className="text-xs font-bold text-amber-400">{signal.iv != null ? `${signal.iv.toFixed(0)}%` : '—'}</p>
          </div>
        </div>

        {/* Max Pain / PCR / Strike */}
        <div className="grid grid-cols-3 gap-1.5 mb-2.5 text-center text-[11px]">
          <div><p className="text-slate-500">Max Pain</p><p className="text-white font-bold">₹{fmtInt(signal.max_pain)}</p></div>
          <div><p className="text-slate-500">PCR</p><p className="text-indigo-400 font-bold">{signal.pcr != null ? signal.pcr.toFixed(2) : '—'}</p></div>
          <div><p className="text-slate-500">Strike</p><p className="text-white font-bold">₹{fmtInt(signal.strike)}</p></div>
        </div>

        {/* Support / Resistance */}
        <div className="flex gap-1.5 mb-2.5">
          <div className="flex-1 bg-emerald-500/10 rounded-md py-1 text-center">
            <p className="text-[9px] text-emerald-400 font-medium flex items-center justify-center gap-1">
              <IconShield size={9} /> Support ₹{fmtInt(signal.support)}
            </p>
          </div>
          <div className="flex-1 bg-rose-500/10 rounded-md py-1 text-center">
            <p className="text-[9px] text-rose-400 font-medium flex items-center justify-center gap-1">
              <IconMapPin size={9} /> Resistance ₹{fmtInt(signal.resistance)}
            </p>
          </div>
        </div>

        {/* Action Badge */}
        <div className={`mb-2.5 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-[13px] font-bold tracking-wide ${
          isBuy ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/25' : 'bg-rose-500/15 text-rose-400 border border-rose-500/25'
        }`}>
          {isBuy ? <IconTriangleUp size={12} /> : <IconTriangleDown size={12} />}
          {isBuy ? 'BUY' : 'SELL'} {isBuy ? 'CE' : 'PE'} — ₹{fmtInt(signal.strike)} STRIKE
        </div>

        {/* Entry / SL / Target */}
        <div className="grid grid-cols-3 gap-1.5 mb-1.5 text-center">
          <div className="bg-slate-900/30 rounded-md py-1.5">
            <p className="text-[9px] text-slate-500 uppercase">Entry</p>
            <p className="text-xs font-bold text-white">₹{fmt(signal.entry)}</p>
          </div>
          <div className="bg-slate-900/30 rounded-md py-1.5">
            <p className="text-[9px] text-slate-500 uppercase">SL</p>
            <p className="text-xs font-bold text-rose-400">₹{fmt(signal.sl)}</p>
          </div>
          <div className="bg-slate-900/30 rounded-md py-1.5">
            <p className="text-[9px] text-slate-500 uppercase">Target</p>
            <p className="text-xs font-bold text-emerald-400">₹{fmt(signal.target1)}</p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between pt-1.5 border-t border-slate-700/30">
          <span className="text-[9px] text-slate-500">Qty: {signal.quantity} · R:R {(signal.risk_reward || 2).toFixed(1)}</span>
          <span className="text-[9px] text-slate-500 group-hover:text-blue-400 transition-colors flex items-center gap-1">
            <IconSearch size={9} /> Dive for full analysis
          </span>
        </div>
      </div>

      {showModal && <OptionsDive signal={signal} onClose={() => setShowModal(false)} />}
    </>
  );
}
