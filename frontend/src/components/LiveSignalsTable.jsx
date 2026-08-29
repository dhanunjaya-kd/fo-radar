import { useMemo, useState } from 'react';

const GRADE_STYLES = {
  'A+': 'text-emerald-400 bg-emerald-500/10',
  'A': 'text-emerald-400 bg-emerald-500/10',
  'B': 'text-lime-400 bg-lime-500/10',
  'C': 'text-amber-400 bg-amber-500/10',
  'D': 'text-rose-400 bg-rose-500/10',
};

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

function buildReason(signal) {
  const parts = [];
  if (signal.rsi != null) parts.push(`RSI ${signal.rsi.toFixed(1)}`);
  if (signal.adx != null) parts.push(`ADX ${signal.adx.toFixed(1)} (trend strength)`);
  if (signal.oi_confirmation) parts.push(`OI ${signal.oi_confirmation}`);
  if (signal.pattern && signal.pattern !== 'None') parts.push(signal.pattern);
  return parts.length > 0 ? parts.join(' · ') : 'No additional detail available';
}

// Aug 28 2026: tested in test_option_label.js -- anchored against the
// ALREADY-KNOWN stock symbol and strike (both real, separate fields)
// rather than a blind regex against the whole option_symbol string.
// Falls back gracefully (no month) if option_symbol is missing or in
// an unexpected shape -- never shows garbage.
function extractExpiryMonth(optionSymbol, stockSymbol, strike) {
  if (!optionSymbol || !stockSymbol || strike == null) return null;
  const cleaned = optionSymbol.replace(/^NSE:/, '');
  if (!cleaned.startsWith(stockSymbol)) return null;
  const afterSymbol = cleaned.slice(stockSymbol.length);
  const strikeStr = String(Math.round(strike));
  const strikeIdx = afterSymbol.indexOf(strikeStr);
  if (strikeIdx < 3) return null;
  const yearAndMonth = afterSymbol.slice(0, strikeIdx);
  const monthMatch = yearAndMonth.match(/^\d{2}([A-Z]{3})$/);
  return monthMatch ? monthMatch[1] : null;
}

function formatOptionContractLabel(signal) {
  const month = extractExpiryMonth(signal.option_symbol, signal.symbol, signal.strike);
  const optSide = signal.action === 'BUY' ? 'CE' : 'PE';
  if (!month) {
    return `${signal.action} ${signal.symbol} ${signal.strike} ${optSide}`;
  }
  return `${signal.action} ${signal.symbol} ${month} ${signal.strike} ${optSide}`;
}

// Aug 28 2026: tested in test_signal_age.js.
function formatSignalAge(timestamp) {
  if (!timestamp) return null;
  const then = new Date(timestamp);
  const diffMs = Date.now() - then;
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function fmtPrice(v) {
  return v != null ? `₹${v.toFixed(2)}` : '—';
}
function fmtNum(v, digits = 1) {
  return v != null ? v.toFixed(digits) : '—';
}

function DetailDrawer({ signal, onClose }) {
  if (!signal) return null;
  const isBuy = signal.action === 'BUY';
  const contractLabel = formatOptionContractLabel(signal);
  const age = formatSignalAge(signal.timestamp);

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
      <div className="fixed top-0 right-0 h-full w-full sm:w-[420px] bg-slate-900 border-l border-slate-700 z-50 overflow-y-auto shadow-2xl">
        <div className="sticky top-0 bg-slate-900 border-b border-slate-700/50 px-4 py-3 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-white">{signal.symbol}</h2>
            <p className="text-xs text-slate-400">
              <span className={`font-bold ${GRADE_STYLES[signal.grade]?.split(' ')[0] || 'text-slate-400'}`}>{signal.grade}</span>
              {' · '}{signal.pattern || 'No pattern'}
            </p>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 text-xl leading-none px-1">✕</button>
        </div>

        <div className="p-4 space-y-4">
          <div className={`rounded-lg p-3 text-center border ${isBuy ? 'bg-emerald-500/10 border-emerald-500/25' : 'bg-rose-500/10 border-rose-500/25'}`}>
            <p className={`text-base font-bold ${isBuy ? 'text-emerald-400' : 'text-rose-400'}`}>{contractLabel}</p>
            <div className="flex items-center justify-center gap-2 mt-1">
              <span className={`text-[10px] px-2 py-0.5 rounded-full border ${statusStyle(signal.outcome_status)}`}>
                {signal.outcome_status || 'Open'}
              </span>
              {age && <span className="text-[10px] text-slate-500">{age}</span>}
            </div>
          </div>

          <div>
            <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1.5">Entry / Exit Levels</p>
            <div className="grid grid-cols-3 gap-2">
              <div className="bg-slate-800/60 rounded-lg p-2 text-center">
                <p className="text-[9px] text-slate-500 uppercase">Entry</p>
                <p className="text-sm font-bold text-white tabular-nums">{fmtPrice(signal.entry)}</p>
              </div>
              <div className="bg-slate-800/60 rounded-lg p-2 text-center">
                <p className="text-[9px] text-slate-500 uppercase">SL</p>
                <p className="text-sm font-bold text-rose-400 tabular-nums">{fmtPrice(signal.sl)}</p>
              </div>
              <div className="bg-slate-800/60 rounded-lg p-2 text-center">
                <p className="text-[9px] text-slate-500 uppercase">R:R</p>
                <p className="text-sm font-bold text-white tabular-nums">{fmtNum(signal.risk_reward)}</p>
              </div>
              <div className="bg-slate-800/60 rounded-lg p-2 text-center">
                <p className="text-[9px] text-slate-500 uppercase">Target 1</p>
                <p className="text-sm font-bold text-emerald-400 tabular-nums">{fmtPrice(signal.target1)}</p>
              </div>
              <div className="bg-slate-800/60 rounded-lg p-2 text-center">
                <p className="text-[9px] text-slate-500 uppercase">Target 2</p>
                <p className="text-sm font-bold text-emerald-400/80 tabular-nums">{fmtPrice(signal.target2)}</p>
              </div>
              <div className="bg-slate-800/60 rounded-lg p-2 text-center">
                <p className="text-[9px] text-slate-500 uppercase">Target 3</p>
                <p className="text-sm font-bold text-emerald-400/60 tabular-nums">{fmtPrice(signal.target3)}</p>
              </div>
            </div>
          </div>

          <div>
            <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1.5">Signal Reason</p>
            <div className="bg-slate-800/60 rounded-lg p-3">
              <p className="text-xs text-slate-300">{buildReason(signal)}</p>
            </div>
          </div>

          <div>
            <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1.5">
              OI Positioning {signal.live_oi === false && <span className="text-amber-500 normal-case">(no live option chain -- price-action fallback shown)</span>}
            </p>
            <div className="bg-slate-800/60 rounded-lg p-3 space-y-1.5 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-500">OI Buildup</span>
                <span className="text-slate-200">{signal.oi_buildup || '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Confirmation</span>
                <span className="text-slate-200">{signal.oi_confirmation || '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">PCR</span>
                <span className="text-slate-200 tabular-nums">{fmtNum(signal.pcr, 2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Max Pain</span>
                <span className="text-slate-200 tabular-nums">{signal.max_pain != null ? signal.max_pain.toLocaleString('en-IN') : '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Support</span>
                <span className="text-emerald-400 tabular-nums">{fmtPrice(signal.support)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Resistance</span>
                <span className="text-rose-400 tabular-nums">{fmtPrice(signal.resistance)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">IV</span>
                <span className="text-slate-200 tabular-nums">{signal.iv != null ? `${signal.iv.toFixed(1)}%` : '—'}</span>
              </div>
            </div>
          </div>

          {(signal.delta != null || signal.theta != null || signal.vega != null || signal.gamma != null) && (
            <div>
              <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1.5">Greeks (at entry strike)</p>
              <div className="grid grid-cols-4 gap-2">
                {[['Delta', signal.delta], ['Theta', signal.theta], ['Vega', signal.vega], ['Gamma', signal.gamma]].map(([label, val]) => (
                  <div key={label} className="bg-slate-800/60 rounded-lg p-2 text-center">
                    <p className="text-[9px] text-slate-500 uppercase">{label}</p>
                    <p className="text-xs font-bold text-white tabular-nums">{val != null ? val.toFixed(3) : '—'}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
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

      {/* Table -- consolidated columns: Symbol carries grade+pattern as
          a subtitle instead of a separate column, and the option
          contract label replaces the old separate Strategy + Action
          columns (it already encodes both). Fewer, richer cells --
          better hierarchy, not more information. */}
      <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[9px] text-slate-500 uppercase border-b border-slate-700/30">
                <th className="text-left px-4 py-2.5 font-medium">Symbol</th>
                <th className="text-left px-2 py-2.5 font-medium">Contract</th>
                <th className="text-right px-2 py-2.5 font-medium">Chg%</th>
                <th className="text-center px-2 py-2.5 font-medium">Status</th>
                <th className="text-right px-2 py-2.5 font-medium">Entry</th>
                <th className="text-right px-2 py-2.5 font-medium">SL</th>
                <th className="text-right px-2 py-2.5 font-medium">T1</th>
                <th className="text-right px-4 py-2.5 font-medium">R:R</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-slate-500">No signals match these filters.</td></tr>
              ) : filtered.map((s) => {
                const isPos = (s.change_percent || 0) >= 0;
                const isBuy = s.action === 'BUY';
                const isSelected = s.symbol === selectedSymbol;
                return (
                  <tr
                    key={s.symbol}
                    onClick={() => setSelectedSymbol(s.symbol)}
                    className={`border-b border-slate-700/20 last:border-0 cursor-pointer transition-colors ${isSelected ? 'bg-slate-700/40' : 'hover:bg-slate-900/30'}`}
                  >
                    <td className="px-4 py-2.5 whitespace-nowrap">
                      <p className="text-white font-semibold">{s.symbol}</p>
                      <p className="text-[10px] text-slate-500 flex items-center gap-1">
                        <span className={`font-bold ${GRADE_STYLES[s.grade]?.split(' ')[0] || 'text-slate-400'}`}>{s.grade}</span>
                        {' · '}{s.pattern || '—'}
                      </p>
                    </td>
                    <td className="px-2 py-2.5 whitespace-nowrap">
                      <span className={`text-[11px] font-semibold ${isBuy ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {formatOptionContractLabel(s)}
                      </span>
                    </td>
                    <td className={`px-2 py-2.5 text-right font-medium tabular-nums ${isPos ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {isPos ? '+' : ''}{s.change_percent != null ? s.change_percent.toFixed(2) : '0.00'}%
                    </td>
                    <td className="px-2 py-2.5 text-center">
                      <span className={`text-[9px] px-1.5 py-0.5 rounded-full border whitespace-nowrap ${statusStyle(s.outcome_status)}`}>{s.outcome_status || 'Open'}</span>
                    </td>
                    <td className="px-2 py-2.5 text-right text-slate-300 tabular-nums">{fmtPrice(s.entry)}</td>
                    <td className="px-2 py-2.5 text-right text-rose-400/80 tabular-nums">{fmtPrice(s.sl)}</td>
                    <td className="px-2 py-2.5 text-right text-emerald-400/80 tabular-nums">{fmtPrice(s.target1)}</td>
                    <td className="px-4 py-2.5 text-right text-slate-300 tabular-nums">{fmtNum(s.risk_reward)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Detail drawer -- slides in from the right on row click, replaces
          the old inline-expanding panel below the table */}
      <DetailDrawer signal={selected} onClose={() => setSelectedSymbol(null)} />
    </div>
  );
}
