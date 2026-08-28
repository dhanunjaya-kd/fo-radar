import { useMemo, useState } from 'react';

const GRADE_STYLES = {
  'A+': 'text-emerald-400 bg-emerald-500/10',
  'A': 'text-emerald-400 bg-emerald-500/10',
  'B': 'text-lime-400 bg-lime-500/10',
  'C': 'text-amber-400 bg-amber-500/10',
  'D': 'text-rose-400 bg-rose-500/10',
};

// Aug 28 2026: tested against every real outcome_status string
// (test_live_signals_logic.js) before this component was written --
// "Confirmed" isn't a real filter bucket here (every signal reaching
// this list already requires OI confirmation as a hard backend
// filter, so it would just duplicate "All") -- these 3 buckets are
// the genuinely varying real states instead.
function statusBucket(outcomeStatus) {
  if (outcomeStatus === 'Open') return 'Open';
  if (outcomeStatus === 'SL Hit') return 'SL Hit';
  if (outcomeStatus && outcomeStatus.startsWith('Target')) return 'Target Hit';
  return 'Open';
}

function statusStyle(status) {
  if (status === 'Open') return 'text-blue-400 bg-blue-500/10 border-blue-500/25';
  if (status === 'SL Hit') return 'text-rose-400 bg-rose-500/10 border-rose-500/25';
  if (status && status.startsWith('Target')) return 'text-emerald-400 bg-emerald-500/10 border-emerald-500/25';
  return 'text-slate-400 bg-slate-500/10 border-slate-500/25';
}

// Aug 28 2026: only claims about a signal that are ACTUALLY present as
// real fields on it -- no fabricated "Price above VWAP" / "Volume
// breakout" style claims that can't be verified from the exposed
// signal object (those specific booleans exist inside _build_all()'s
// scoring logic but were never exposed per-signal in the API
// response). Tested against full/sparse/empty signals before use.
function buildReason(signal) {
  const parts = [];
  if (signal.rsi != null) parts.push(`RSI ${signal.rsi.toFixed(1)}`);
  if (signal.adx != null) parts.push(`ADX ${signal.adx.toFixed(1)} (trend strength)`);
  if (signal.oi_confirmation) parts.push(`OI ${signal.oi_confirmation}`);
  if (signal.pattern && signal.pattern !== 'None') parts.push(signal.pattern);
  return parts.length > 0 ? parts.join(' · ') : 'No additional detail available';
}

export default function LiveSignalsTable({ signals }) {
  const [statusFilter, setStatusFilter] = useState('All');
  const [gradeFilter, setGradeFilter] = useState('All');
  const [sectorFilter, setSectorFilter] = useState('All');
  const [selectedSymbol, setSelectedSymbol] = useState(null);

  const grades = useMemo(() => ['All', ...new Set(signals.map(s => s.grade).filter(Boolean))], [signals]);
  const sectors = useMemo(() => ['All', ...new Set(signals.map(s => s.sector).filter(Boolean))].sort(), [signals]);

  const statusCounts = useMemo(() => {
    const counts = { All: signals.length, Open: 0, 'Target Hit': 0, 'SL Hit': 0 };
    for (const s of signals) counts[statusBucket(s.outcome_status)]++;
    return counts;
  }, [signals]);

  const filtered = useMemo(() => {
    return signals.filter(s => {
      if (statusFilter !== 'All' && statusBucket(s.outcome_status) !== statusFilter) return false;
      if (gradeFilter !== 'All' && s.grade !== gradeFilter) return false;
      if (sectorFilter !== 'All' && s.sector !== sectorFilter) return false;
      return true;
    });
  }, [signals, statusFilter, gradeFilter, sectorFilter]);

  const selected = filtered.find(s => s.symbol === selectedSymbol) || null;

  return (
    <div className="space-y-3">
      {/* Status filter tabs -- real buckets, real counts */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {['All', 'Open', 'Target Hit', 'SL Hit'].map(bucket => (
          <button
            key={bucket}
            onClick={() => setStatusFilter(bucket)}
            className={`text-xs font-medium px-3 py-1.5 rounded-lg border transition-colors ${
              statusFilter === bucket
                ? 'bg-slate-700 text-white border-slate-600'
                : 'bg-slate-800/50 text-slate-400 border-slate-700/50 hover:text-slate-200'
            }`}
          >
            {bucket} <span className="text-slate-500">{statusCounts[bucket] ?? 0}</span>
          </button>
        ))}
        <div className="flex-1" />
        <select value={gradeFilter} onChange={(e) => setGradeFilter(e.target.value)}
          className="text-xs bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-slate-300 focus:outline-none focus:border-emerald-500">
          {grades.map(g => <option key={g} value={g}>{g === 'All' ? 'All Grades' : `Grade ${g}`}</option>)}
        </select>
        <select value={sectorFilter} onChange={(e) => setSectorFilter(e.target.value)}
          className="text-xs bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-slate-300 focus:outline-none focus:border-emerald-500">
          {sectors.map(s => <option key={s} value={s}>{s === 'All' ? 'All Sectors' : s}</option>)}
        </select>
      </div>

      {/* Table */}
      <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[9px] text-slate-500 uppercase border-b border-slate-700/30">
                <th className="text-left px-4 py-2.5 font-medium">Symbol</th>
                <th className="text-left px-2 py-2.5 font-medium">Strategy</th>
                <th className="text-right px-2 py-2.5 font-medium">Price</th>
                <th className="text-right px-2 py-2.5 font-medium">Chg%</th>
                <th className="text-center px-2 py-2.5 font-medium">Grade</th>
                <th className="text-center px-2 py-2.5 font-medium">Status</th>
                <th className="text-right px-2 py-2.5 font-medium">Entry</th>
                <th className="text-right px-2 py-2.5 font-medium">SL</th>
                <th className="text-right px-2 py-2.5 font-medium">Target 1</th>
                <th className="text-right px-2 py-2.5 font-medium">R:R</th>
                <th className="text-right px-4 py-2.5 font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr><td colSpan={11} className="px-4 py-8 text-center text-slate-500">No signals match these filters.</td></tr>
              ) : filtered.map((s) => {
                const isPos = (s.change_percent || 0) >= 0;
                const isBuy = s.action === 'BUY';
                const isSelected = s.symbol === selectedSymbol;
                return (
                  <tr
                    key={s.symbol}
                    onClick={() => setSelectedSymbol(isSelected ? null : s.symbol)}
                    className={`border-b border-slate-700/20 last:border-0 cursor-pointer transition-colors ${isSelected ? 'bg-slate-700/40' : 'hover:bg-slate-900/30'}`}
                  >
                    <td className="px-4 py-2.5 text-white font-medium whitespace-nowrap">{s.symbol}</td>
                    <td className="px-2 py-2.5 text-slate-400 whitespace-nowrap">{s.pattern || '—'}</td>
                    <td className="px-2 py-2.5 text-right text-slate-300 tabular-nums">₹{s.price != null ? s.price.toFixed(2) : '—'}</td>
                    <td className={`px-2 py-2.5 text-right font-medium tabular-nums ${isPos ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {isPos ? '+' : ''}{s.change_percent != null ? s.change_percent.toFixed(2) : '0.00'}%
                    </td>
                    <td className="px-2 py-2.5 text-center">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${GRADE_STYLES[s.grade] || GRADE_STYLES['C']}`}>{s.grade}</span>
                    </td>
                    <td className="px-2 py-2.5 text-center">
                      <span className={`text-[9px] px-1.5 py-0.5 rounded-full border whitespace-nowrap ${statusStyle(s.outcome_status)}`}>{s.outcome_status || 'Open'}</span>
                    </td>
                    <td className="px-2 py-2.5 text-right text-slate-300 tabular-nums">₹{s.entry != null ? s.entry.toFixed(2) : '—'}</td>
                    <td className="px-2 py-2.5 text-right text-rose-400/80 tabular-nums">₹{s.sl != null ? s.sl.toFixed(2) : '—'}</td>
                    <td className="px-2 py-2.5 text-right text-emerald-400/80 tabular-nums">₹{s.target1 != null ? s.target1.toFixed(2) : '—'}</td>
                    <td className="px-2 py-2.5 text-right text-slate-300 tabular-nums">{s.risk_reward != null ? s.risk_reward.toFixed(1) : '—'}</td>
                    <td className="px-4 py-2.5 text-right">
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${isBuy ? 'text-emerald-400 bg-emerald-500/10' : 'text-rose-400 bg-rose-500/10'}`}>
                        {isBuy ? 'BUY' : 'SELL'}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Detail panel -- appears when a row is clicked */}
      {selected && (
        <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              {selected.symbol}
              <span className={`text-[10px] px-2 py-0.5 rounded-full border ${statusStyle(selected.outcome_status)}`}>
                {selected.outcome_status || 'Open'}
              </span>
              <span>{selected.action === 'BUY' ? '🟢' : '🔴'} {selected.recommendation}</span>
            </h3>
            <button onClick={() => setSelectedSymbol(null)} className="text-slate-500 hover:text-slate-300 text-xs">✕ Close</button>
          </div>
          <div className="grid grid-cols-3 md:grid-cols-6 gap-2 mb-3">
            {[
              ['Price', selected.price != null ? `₹${selected.price.toFixed(2)}` : '—'],
              ['Entry', selected.entry != null ? `₹${selected.entry.toFixed(2)}` : '—'],
              ['SL', selected.sl != null ? `₹${selected.sl.toFixed(2)}` : '—'],
              ['Target 1', selected.target1 != null ? `₹${selected.target1.toFixed(2)}` : '—'],
              ['R:R', selected.risk_reward != null ? selected.risk_reward.toFixed(1) : '—'],
              ['Confidence', selected.confidence || '—'],
            ].map(([label, value]) => (
              <div key={label} className="bg-slate-900/40 rounded-lg p-2 text-center">
                <p className="text-[9px] text-slate-500 uppercase">{label}</p>
                <p className="text-sm font-bold text-white tabular-nums">{value}</p>
              </div>
            ))}
          </div>
          <div className="bg-slate-900/40 rounded-lg p-3">
            <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1">Reason</p>
            <p className="text-xs text-slate-300">{buildReason(selected)}</p>
          </div>
          {selected.timestamp && (
            <p className="text-[10px] text-slate-500 mt-2">
              Generated {new Date(selected.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
