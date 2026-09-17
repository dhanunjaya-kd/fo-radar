import { useEffect, useMemo, useState } from 'react';
import OptionPriceChart from './OptionPriceChart';

const API_BASE = import.meta.env.VITE_API_URL || '';

const GRADE_STYLES = {
  'A+': 'text-emerald-400 bg-emerald-500/10',
  'A': 'text-emerald-400 bg-emerald-500/10',
  'B': 'text-lime-400 bg-lime-500/10',
  'C': 'text-amber-400 bg-amber-500/10',
  'D': 'text-rose-400 bg-rose-500/10',
};

const TECH_TONE = { Bullish: 'green', Neutral: 'gray', Bearish: 'red' };

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
  if (!month) return `${signal.action} ${signal.symbol} ${signal.strike} ${optSide}`;
  return `${signal.action} ${signal.symbol} ${month} ${signal.strike} ${optSide}`;
}

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

function fmtPrice(v) { return v != null ? `₹${v.toFixed(2)}` : '—'; }
function fmtNum(v, digits = 1) { return v != null ? v.toFixed(digits) : '—'; }

function previewValue(value, formatter) {
  if (value == null || value === '') return '—';
  return formatter ? formatter(value) : String(value);
}

function DetailDrawer({ signal, onClose }) {
  const [rangeData, setRangeData] = useState(null);
  const [fyersOpened, setFyersOpened] = useState(false);

  useEffect(() => {
    if (!signal) { setRangeData(null); return; }
    let cancelled = false;
    fetch(`${API_BASE}/api/52-week-range/${signal.symbol}/`)
      .then(res => res.ok ? res.json() : Promise.reject(new Error('HTTP ' + res.status)))
      .then(data => { if (!cancelled) setRangeData(data); })
      .catch(() => { if (!cancelled) setRangeData(null); });
    return () => { cancelled = true; };
  }, [signal?.symbol]);

  if (!signal) return null;
  const isBuy = signal.action === 'BUY';
  const contractLabel = formatOptionContractLabel(signal);
  const age = formatSignalAge(signal.timestamp);

  const handleOpenChart = () => {
    // We intentionally open the signal's underlying NSE equity, not the option strike.
    // If the optional FYERS Stock Opener extension is installed, it handles the
    // navigation itself. Avoid opening a second FYERS tab, which could race the
    // extension and leave the wrong/default chart visible.
    const underlyingSymbol = signal.symbol ? `NSE:${signal.symbol}-EQ` : null;
    if (!underlyingSymbol) return;

    try {
      navigator.clipboard.writeText(underlyingSymbol);
    } catch (_) {
      // Clipboard is only a convenience.
    }

    const extensionInstalled = document.documentElement.dataset.fyersStockExtension === '1';
    if (extensionInstalled) {
      document.dispatchEvent(new CustomEvent('fyers-stock-open', {
        detail: { symbol: underlyingSymbol },
        bubbles: true,
      }));
    } else {
      window.open('https://trade.fyers.in/', '_blank', 'noopener,noreferrer');
    }

    setFyersOpened(true);
    setTimeout(() => setFyersOpened(false), 3500);
  };

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
            <button
              onClick={handleOpenChart}
              disabled={!signal.symbol}
              title={signal.symbol ? `Open ${signal.symbol} stock in FYERS` : 'Stock symbol unavailable'}
              className={`text-base font-bold underline decoration-dotted underline-offset-2 hover:opacity-80 transition-opacity disabled:opacity-50 ${isBuy ? 'text-emerald-400' : 'text-rose-400'}`}
            >
              {contractLabel}
            </button>
            <div className="flex items-center justify-center gap-2 mt-1">
              <span className={`text-[10px] px-2 py-0.5 rounded-full border ${statusStyle(signal.outcome_status)}`}>
                {signal.outcome_status || 'Open'}
              </span>
              {age && <span className="text-[10px] text-slate-500">{age}</span>}
            </div>
            <p className="text-[9px] text-slate-500 mt-1.5">
              {fyersOpened
                ? `✓ NSE:${signal.symbol}-EQ copied — FYERS opened`
                : signal.symbol
                  ? `Click to open ${signal.symbol} stock in FYERS`
                  : `Stock symbol unavailable`}
            </p>
            {signal.near_expiry_warning === true && (
              <p className="text-[10px] text-amber-400 text-center mt-1">
                ⚠ Near expiry — theta decay and pin risk both elevated
              </p>
            )}
          </div>

          {signal.option_symbol && <OptionPriceChart optionSymbol={signal.option_symbol} />}

          <div>
            <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1.5">Entry / Exit Levels</p>
            <div className="grid grid-cols-3 gap-2">
              <div className="bg-slate-800/60 rounded-lg p-2 text-center"><p className="text-[9px] text-slate-500 uppercase">Entry</p><p className="text-sm font-bold text-white tabular-nums">{fmtPrice(signal.entry)}</p></div>
              <div className="bg-slate-800/60 rounded-lg p-2 text-center"><p className="text-[9px] text-slate-500 uppercase">SL</p><p className="text-sm font-bold text-rose-400 tabular-nums">{fmtPrice(signal.sl)}</p></div>
              <div className="bg-slate-800/60 rounded-lg p-2 text-center"><p className="text-[9px] text-slate-500 uppercase">R:R</p><p className="text-sm font-bold text-white tabular-nums">{fmtNum(signal.risk_reward)}</p></div>
              <div className="bg-slate-800/60 rounded-lg p-2 text-center"><p className="text-[9px] text-slate-500 uppercase">Target 1</p><p className="text-sm font-bold text-emerald-400 tabular-nums">{fmtPrice(signal.target1)}</p></div>
              <div className="bg-slate-800/60 rounded-lg p-2 text-center"><p className="text-[9px] text-slate-500 uppercase">Target 2</p><p className="text-sm font-bold text-emerald-400/80 tabular-nums">{fmtPrice(signal.target2)}</p></div>
              <div className="bg-slate-800/60 rounded-lg p-2 text-center"><p className="text-[9px] text-slate-500 uppercase">Target 3</p><p className="text-sm font-bold text-emerald-400/60 tabular-nums">{fmtPrice(signal.target3)}</p></div>
            </div>
            {(signal.risk_amount != null || signal.reward_amount != null) && <p className="text-[10px] text-slate-500 text-center mt-1.5">Risk ₹{signal.risk_amount != null ? signal.risk_amount.toLocaleString('en-IN') : '—'}{' · '}Reward ₹{signal.reward_amount != null ? signal.reward_amount.toLocaleString('en-IN') : '—'}{signal.price_basis === 'option_premium' && ' (Option Premium)'}</p>}
            {signal.target1_beyond_resistance === true && <p className="text-[10px] text-amber-400 text-center mt-1">⚠ Target 1 requires clearing {isBuy ? 'resistance' : 'support'} first</p>}
          </div>

          {(signal.stock_vs_sector_pct != null || signal.stock_vs_index_pct != null) && (
            <div><p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1.5">Relative Strength</p><div className="bg-slate-800/60 rounded-lg p-3 flex items-center justify-around text-center"><div><p className="text-[9px] text-slate-500">vs Sector</p><p className={`text-sm font-bold tabular-nums ${signal.stock_vs_sector_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{signal.stock_vs_sector_pct != null ? `${signal.stock_vs_sector_pct >= 0 ? '+' : ''}${signal.stock_vs_sector_pct}%` : '—'}</p></div><div><p className="text-[9px] text-slate-500">vs NIFTY</p><p className={`text-sm font-bold tabular-nums ${signal.stock_vs_index_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{signal.stock_vs_index_pct != null ? `${signal.stock_vs_index_pct >= 0 ? '+' : ''}${signal.stock_vs_index_pct}%` : '—'}</p></div></div></div>
          )}

          <div><p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1.5">52-Week Range &amp; Technical</p><div className="bg-slate-800/60 rounded-lg p-3 flex items-center justify-between">{rangeData?.high52w != null ? <p className="text-xs text-slate-300"><span className="text-emerald-400 font-semibold">₹{rangeData.high52w.toFixed(2)}</span>{' / '}<span className="text-rose-400 font-semibold">₹{rangeData.low52w.toFixed(2)}</span></p> : <p className="text-xs text-slate-500">—</p>}{rangeData?.technical?.label ? <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${TECH_TONE[rangeData.technical.label] === 'green' ? 'text-emerald-400 bg-emerald-500/15 border border-emerald-500/25' : TECH_TONE[rangeData.technical.label] === 'red' ? 'text-rose-400 bg-rose-500/15 border border-rose-500/25' : 'text-slate-400 bg-slate-700/30 border border-slate-600/30'}`}>{rangeData.technical.label}</span> : <span className="text-[10px] text-slate-600">—</span>}</div></div>

          <div><p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1.5">Why this signal</p><div className="bg-slate-800/60 rounded-lg p-3 text-xs text-slate-300 leading-relaxed">{buildReason(signal)}</div></div>
        </div>
      </div>
    </>
  );
}

export default function LiveSignalsTable({ signals = [], onSignalClick }) {
  const [selected, setSelected] = useState(null);
  const visibleSignals = useMemo(() => signals || [], [signals]);
  if (!visibleSignals.length) return <div className="text-sm text-slate-500 py-8 text-center">No active signals</div>;

  return <>
    <div className="space-y-2">
      {visibleSignals.map((signal, i) => {
        const isBuy = signal.action === 'BUY';
        const actionTone = isBuy
          ? {
              glow: 'from-emerald-400/10 via-emerald-500/5 to-transparent',
              line: 'bg-emerald-400/20',
              metric: 'text-emerald-300',
            }
          : {
              glow: 'from-rose-400/10 via-rose-500/5 to-transparent',
              line: 'bg-rose-400/20',
              metric: 'text-rose-300',
            };

        return (
          <button
            key={`${signal.symbol}-${signal.timestamp || i}`}
            onClick={() => { setSelected(signal); onSignalClick?.(signal); }}
            className="group relative w-full overflow-hidden text-left rounded-xl border border-slate-800 bg-slate-900/55 hover:bg-slate-800/70 hover:border-amber-400/40 hover:-translate-y-0.5 hover:shadow-[0_16px_40px_rgba(0,0,0,0.28)] p-3 transition-all duration-200"
          >
            {/* Hover background layer inspired by the reference scanner UI.
                It stays behind the foreground card content and is purely visual. */}
            <div className={`absolute inset-0 bg-gradient-to-br ${actionTone.glow} opacity-0 group-hover:opacity-100 transition-opacity duration-300`} />
            <div className="pointer-events-none absolute -right-14 -top-16 h-36 w-36 rounded-full border border-white/5 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
            <div className="pointer-events-none absolute right-6 top-3 text-[34px] font-black tracking-tighter text-white/[0.025] opacity-0 group-hover:opacity-100 transition-opacity duration-300 select-none">
              {signal.grade || '—'}
            </div>
            <div className="pointer-events-none absolute inset-x-3 bottom-2 grid grid-cols-4 gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity duration-300">
              {[
                ['RSI', previewValue(signal.rsi, value => Number(value).toFixed(0))],
                ['ADX', previewValue(signal.adx, value => Number(value).toFixed(0))],
                ['OI', signal.oi_confirmation || '—'],
                ['Q', signal.quality_verdict || (signal.quality_score != null ? String(signal.quality_score) : '—')],
              ].map(([label, value]) => (
                <div key={label} className="rounded-md border border-white/5 bg-black/20 px-2 py-1.5 backdrop-blur-[2px]">
                  <div className="text-[8px] uppercase tracking-widest text-slate-500">{label}</div>
                  <div className={`mt-0.5 truncate text-[10px] font-semibold ${actionTone.metric}`}>{value}</div>
                </div>
              ))}
            </div>

            <div className="relative z-10 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-semibold text-white">{signal.symbol}</div>
                <div className="text-[11px] text-slate-500">{formatOptionContractLabel(signal)}</div>
                {(signal.pattern || signal.quality_verdict) && (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {signal.pattern && signal.pattern !== 'None' && (
                      <span className="text-[9px] rounded-full border border-slate-700/80 bg-slate-800/70 px-2 py-0.5 text-slate-400">
                        {signal.pattern}
                      </span>
                    )}
                    {signal.quality_verdict && (
                      <span className={`text-[9px] rounded-full border px-2 py-0.5 ${signal.quality_verdict === 'TRADE'
                        ? 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20'
                        : signal.quality_verdict === 'WATCH'
                          ? 'text-amber-300 bg-amber-500/10 border-amber-500/20'
                          : 'text-rose-300 bg-rose-500/10 border-rose-500/20'
                      }`}>
                        Quality {signal.quality_verdict}{signal.quality_score != null ? ` · ${signal.quality_score}` : ''}
                      </span>
                    )}
                  </div>
                )}
              </div>

              <div className="shrink-0 text-right">
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${GRADE_STYLES[signal.grade] || 'text-slate-400 bg-slate-700/30'}`}>{signal.grade || '—'}</span>
                <div className="text-xs text-slate-400 mt-1">{statusBucket(signal.outcome_status)}</div>
                <div className="text-[10px] text-slate-600 mt-1">{signal.confidence != null ? `${signal.confidence} confidence` : 'Open details'}</div>
              </div>
            </div>

            <div className={`pointer-events-none absolute left-0 top-0 bottom-0 w-px ${actionTone.line} opacity-0 group-hover:opacity-100 transition-opacity duration-300`} />
          </button>
        );
      })}
    </div>
    {selected && <DetailDrawer signal={selected} onClose={() => setSelected(null)} />}
  </>;
}
