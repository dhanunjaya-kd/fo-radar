import ChartCore from './ChartCore';

// Sep 19 2026: now a thin modal wrapper -- the actual chart (fetch,
// candles, EMA, RSI) lives in ChartCore.jsx, shared with the new
// full-page Charts tab so the two never drift into two different
// implementations of the same thing.
export default function ChartModal({ symbol, onClose }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="relative bg-slate-900 border border-slate-800 rounded-xl w-full max-w-3xl max-h-[90vh] overflow-y-auto p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <button onClick={onClose} className="absolute top-3 right-3 z-10 text-slate-500 hover:text-white text-xl leading-none" aria-label="Close">×</button>
        <ChartCore symbol={symbol} />
      </div>
    </div>
  );
}
