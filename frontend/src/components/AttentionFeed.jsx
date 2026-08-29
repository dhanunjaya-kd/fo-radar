import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Aug 28 2026: tested in test_attention_feed.js. Two honest
// categories -- no fake "recently resolved, 3 minutes ago" claim,
// since signals carry no resolution timestamp, only when they were
// first GENERATED. "Today" is as precise as this can honestly be.
function buildAttentionItems(signals) {
  const resolved = signals.filter(s => s.outcome_status && s.outcome_status !== 'Open');
  const highConviction = signals
    .filter(s => s.outcome_status === 'Open' && (s.grade === 'A+' || s.grade === 'A'))
    .sort((a, b) => parseInt(b.confidence) - parseInt(a.confidence));
  return { resolved, highConviction };
}

function outcomeTone(status) {
  if (status === 'SL Hit') return 'text-rose-400';
  if (status && status.startsWith('Target')) return 'text-emerald-400';
  return 'text-slate-400';
}

export default function AttentionFeed({ onNavigate }) {
  const [signals, setSignals] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/sniper-only/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (mounted) setSignals(json.signals || []);
      } catch (err) {
        console.error('Attention feed fetch error:', err);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 60000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (loading) {
    return <div className="h-40 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />;
  }

  const { resolved, highConviction } = buildAttentionItems(signals || []);
  const hasAnything = resolved.length > 0 || highConviction.length > 0;

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-white">⚠ Needs Attention</h3>
        {onNavigate && (
          <button onClick={() => onNavigate('signals')} className="text-[11px] text-blue-400 hover:text-blue-300">
            View All →
          </button>
        )}
      </div>

      {!hasAnything ? (
        <p className="text-xs text-slate-500 text-center py-3">Nothing needs attention right now.</p>
      ) : (
        <div className="space-y-3">
          {resolved.length > 0 && (
            <div>
              <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1.5">Resolved Today</p>
              <div className="space-y-1">
                {resolved.slice(0, 4).map(s => (
                  <div key={s.symbol} className="flex items-center justify-between text-xs">
                    <span className="text-white font-medium">{s.symbol}</span>
                    <span className={`font-semibold ${outcomeTone(s.outcome_status)}`}>{s.outcome_status}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {highConviction.length > 0 && (
            <div>
              <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1.5">High Conviction, Still Open</p>
              <div className="space-y-1">
                {highConviction.slice(0, 4).map(s => (
                  <div key={s.symbol} className="flex items-center justify-between text-xs">
                    <span className="text-white font-medium">{s.symbol}</span>
                    <span className="text-emerald-400 font-semibold">{s.grade} · {s.confidence}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
