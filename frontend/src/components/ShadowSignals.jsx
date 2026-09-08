import { useEffect, useState, useMemo, Fragment } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

const AGREEMENT_STYLES = {
  AGREE: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/25',
  V3_ONLY: 'text-amber-400 bg-amber-500/10 border-amber-500/25',
  QUALITY_ONLY: 'text-blue-400 bg-blue-500/10 border-blue-500/25',
};
const AGREEMENT_LABELS = {
  AGREE: 'Agree',
  V3_ONLY: 'v3.0 only',
  QUALITY_ONLY: 'Quality only',
};

const GRADE_STYLES = {
  'A+': 'text-emerald-400', 'A': 'text-emerald-400', 'B': 'text-lime-400',
  'C': 'text-amber-400', 'D': 'text-rose-400',
};

function fmtScore(v) {
  return v != null ? v : '—';
}

function fmtPct(v) {
  if (v == null) return '—';
  const n = Number(v);
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}

export default function ShadowSignals() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all'); // 'all' | 'disagree'
  const [expandedKey, setExpandedKey] = useState(null);

  useEffect(() => {
    let mounted = true;
    const load = () => {
      fetch(`${API_BASE}/api/shadow-signals/`)
        .then((res) => (res.ok ? res.json() : Promise.reject(new Error('HTTP ' + res.status))))
        .then((json) => { if (mounted) { setData(json); setError(null); } })
        .catch((err) => { if (mounted) setError(err.message); })
        .finally(() => { if (mounted) setLoading(false); });
    };
    load();
    const interval = setInterval(load, 60000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  const rows = useMemo(() => {
    const all = data?.candidates || [];
    if (filter === 'disagree') {
      return all.filter((r) => r.Agreement === 'V3_ONLY' || r.Agreement === 'QUALITY_ONLY');
    }
    return all;
  }, [data, filter]);

  if (loading && !data) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => <div key={i} className="h-14 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />)}
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="text-center py-16">
        <p className="text-sm text-rose-400">Couldn't load shadow signals: {error}</p>
      </div>
    );
  }

  const summary = data?.agreement_summary || { AGREE: 0, V3_ONLY: 0, QUALITY_ONLY: 0 };

  return (
    <div className="space-y-3">
      {/* Sep 8 2026: SHADOW MODE is purely observational -- this view
          shows v3.0's real decision next to quality_engine.py's
          independent assessment for every candidate _build_all()
          evaluated today. Nothing here has ever fed back into v3.0's
          own live signal selection. */}
      <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-3">
        <p className="text-xs text-slate-400 leading-relaxed">
          <span className="text-slate-200 font-semibold">Shadow Mode</span> — v3.0's real decision vs. the new Quality Engine's independent assessment, side by side, for every candidate evaluated today. Purely observational: nothing here has ever changed a live signal.
        </p>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex gap-1.5">
          {['AGREE', 'V3_ONLY', 'QUALITY_ONLY'].map((k) => (
            <span key={k} className={`text-[11px] font-semibold px-2.5 py-1 rounded-full border whitespace-nowrap ${AGREEMENT_STYLES[k]}`}>
              {AGREEMENT_LABELS[k]}: {summary[k] || 0}
            </span>
          ))}
        </div>
        <div className="flex gap-1 ml-auto">
          <button
            onClick={() => setFilter('all')}
            className={`text-xs px-3 py-1.5 rounded-lg border ${filter === 'all' ? 'bg-slate-700 text-white border-slate-600' : 'text-slate-400 border-slate-700 hover:text-slate-200'}`}
          >
            All ({data?.count || 0})
          </button>
          <button
            onClick={() => setFilter('disagree')}
            className={`text-xs px-3 py-1.5 rounded-lg border ${filter === 'disagree' ? 'bg-slate-700 text-white border-slate-600' : 'text-slate-400 border-slate-700 hover:text-slate-200'}`}
          >
            Disagreements only ({(summary.V3_ONLY || 0) + (summary.QUALITY_ONLY || 0)})
          </button>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-sm text-slate-500">
            {filter === 'disagree' ? 'No disagreements yet today.' : 'No shadow candidates logged yet today.'}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-slate-900/60 text-slate-500 text-[10px] uppercase tracking-wide">
                <th className="text-left px-3 py-2 font-medium">Time</th>
                <th className="text-left px-3 py-2 font-medium">Symbol</th>
                <th className="text-center px-2 py-2 font-medium">Action</th>
                <th className="text-center px-2 py-2 font-medium">v3.0</th>
                <th className="text-right px-2 py-2 font-medium">v3 Score</th>
                <th className="text-center px-2 py-2 font-medium">Quality</th>
                <th className="text-right px-2 py-2 font-medium">Q Score</th>
                <th className="text-center px-2 py-2 font-medium">Agreement</th>
                <th className="text-right px-2 py-2 font-medium">MFE</th>
                <th className="text-right px-2 py-2 font-medium">MAE</th>
                <th className="text-center px-3 py-2 font-medium">Why</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const rowKey = `${r.Symbol}-${r.Action}-${i}`;
                const isExpanded = expandedKey === rowKey;
                const reasonList = (r.Reasons || '').split(';').map((s) => s.trim()).filter(Boolean);
                return (
                  <Fragment key={rowKey}>
                    <tr
                      onClick={() => reasonList.length > 0 && setExpandedKey(isExpanded ? null : rowKey)}
                      className={`border-t border-slate-800/60 hover:bg-slate-900/40 transition-colors ${reasonList.length > 0 ? 'cursor-pointer' : ''}`}
                    >
                      <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{r.Timestamp ? r.Timestamp.split(' ')[1] : '—'}</td>
                      <td className="px-3 py-2 text-white font-medium whitespace-nowrap">{r.Symbol}</td>
                      <td className="px-2 py-2 text-center">
                        <span className={r.Action === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}>{r.Action}</span>
                      </td>
                      <td className="px-2 py-2 text-center whitespace-nowrap" title={r['V3 Reason'] || ''}>
                        {r['V3 Decision'] === 'SIGNAL'
                          ? <span className={`font-semibold ${GRADE_STYLES[r['V3 Grade']] || 'text-slate-300'}`}>{r['V3 Grade'] || 'Signal'}</span>
                          : <span className="text-slate-500">No trade</span>}
                      </td>
                      <td className="px-2 py-2 text-right text-slate-300 tabular-nums">{fmtScore(r['V3 Score'])}</td>
                      <td className="px-2 py-2 text-center whitespace-nowrap">
                        {r['Quality Verdict'] === 'TRADE'
                          ? <span className={`font-semibold ${GRADE_STYLES[r['Quality Grade']] || 'text-slate-300'}`}>{r['Quality Grade'] || 'Trade'}</span>
                          : r['Quality Verdict'] === 'WATCH'
                            ? <span className="text-amber-400">Watch</span>
                            : <span className="text-slate-500">Ignore</span>}
                      </td>
                      <td className="px-2 py-2 text-right text-slate-300 tabular-nums">{fmtScore(r['Quality Score'])}</td>
                      <td className="px-2 py-2 text-center">
                        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full border whitespace-nowrap ${AGREEMENT_STYLES[r.Agreement] || 'text-slate-400 bg-slate-700/30 border-slate-600/30'}`}>
                          {AGREEMENT_LABELS[r.Agreement] || r.Agreement || '—'}
                        </span>
                      </td>
                      <td className="px-2 py-2 text-right text-emerald-400 tabular-nums">{fmtPct(r['MFE %'])}</td>
                      <td className="px-2 py-2 text-right text-rose-400 tabular-nums">{fmtPct(r['MAE %'])}</td>
                      <td className="px-3 py-2 text-center text-slate-500">
                        {reasonList.length > 0 ? (isExpanded ? '▲' : '▼') : '—'}
                      </td>
                    </tr>
                    {isExpanded && reasonList.length > 0 && (
                      <tr className="bg-slate-900/40 border-t border-slate-800/40">
                        <td colSpan={11} className="px-4 py-2.5">
                          <ul className="space-y-1">
                            {reasonList.map((reason, ri) => {
                              const isWarning = reason.toLowerCase().includes('gate') || reason.toLowerCase().includes('extended')
                                || reason.toLowerCase().includes('weak') || reason.toLowerCase().includes('against') || reason.toLowerCase().includes('conflict');
                              return (
                                <li key={ri} className={`text-xs flex items-start gap-1.5 ${isWarning ? 'text-amber-400' : 'text-slate-300'}`}>
                                  <span className="shrink-0">{isWarning ? '⚠' : '✓'}</span>
                                  <span>{reason}</span>
                                </li>
                              );
                            })}
                          </ul>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
