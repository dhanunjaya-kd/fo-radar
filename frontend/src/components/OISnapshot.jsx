import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Same PCR sentiment classification already used in OptionsOverview.jsx
// -- reused verbatim, not re-derived.
function pcrSentiment(pcr) {
  if (pcr == null) return { label: 'N/A', tone: 'text-slate-400' };
  if (pcr > 1.05) return { label: 'Bullish', tone: 'text-emerald-400' };
  if (pcr < 0.95) return { label: 'Bearish', tone: 'text-rose-400' };
  return { label: 'Neutral', tone: 'text-amber-400' };
}

export default function OISnapshot({ onNavigate }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/option-analytics/NIFTY/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (mounted) setData(json.live === false ? null : json);
      } catch (err) {
        console.error('OI snapshot fetch error:', err);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (loading) {
    return <div className="h-24 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />;
  }

  const sentiment = data ? pcrSentiment(data.pcr) : null;

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-bold text-white">NIFTY OI Positioning</h3>
        {onNavigate && (
          <button onClick={() => onNavigate('oi')} className="text-[11px] text-blue-400 hover:text-blue-300">
            Details →
          </button>
        )}
      </div>
      {!data ? (
        <p className="text-xs text-slate-500 text-center py-2">No live option chain available right now.</p>
      ) : (
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[9px] text-slate-500 uppercase">PCR</p>
            <p className={`text-lg font-bold ${sentiment.tone}`}>{data.pcr != null ? data.pcr.toFixed(2) : '—'}</p>
          </div>
          <div className="text-right">
            <p className="text-[9px] text-slate-500 uppercase">Sentiment</p>
            <p className={`text-sm font-semibold ${sentiment.tone}`}>{sentiment.label}</p>
          </div>
          <div className="text-right">
            <p className="text-[9px] text-slate-500 uppercase">Max Pain</p>
            <p className="text-sm font-bold text-white tabular-nums">{data.maxPain != null ? data.maxPain.toLocaleString('en-IN') : '—'}</p>
          </div>
        </div>
      )}
    </div>
  );
}
