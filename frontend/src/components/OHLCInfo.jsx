import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Aug 28 2026: Open/High/Low derived from today's already-fetched
// snapshots -- tested in test_ohlc_derivation.js before this
// component was written. No new backend endpoint: this reuses the
// exact same /api/index-tracker/<name>/ (today) and .../?date=X
// (previous day, for Prev Close) endpoints IndexPriceChart.jsx and
// the main snapshot table already call.
function deriveOHLC(todaySnapshots, prevDaySnapshots) {
  if (!todaySnapshots || todaySnapshots.length === 0) return null;
  const spots = todaySnapshots.map(r => r.Spot).filter(v => v != null && !isNaN(v));
  if (spots.length === 0) return null;
  const open = todaySnapshots[todaySnapshots.length - 1].Spot;
  const high = Math.max(...spots);
  const low = Math.min(...spots);
  let prevClose = null;
  if (prevDaySnapshots && prevDaySnapshots.length > 0) {
    prevClose = prevDaySnapshots[0].Spot;
  }
  return { open, high, low, prevClose };
}

function fmt(n) {
  if (n == null || isNaN(n)) return '—';
  return Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

export default function OHLCInfo({ indexName }) {
  const [ohlc, setOhlc] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const load = async () => {
      try {
        const [todayRes, datesRes] = await Promise.all([
          fetch(`${API_BASE}/api/index-tracker/${indexName}/`).then(r => r.json()),
          fetch(`${API_BASE}/api/index-tracker/${indexName}/dates/`).then(r => r.json()),
        ]);
        const todaySnapshots = todayRes.snapshots || [];
        const dates = (datesRes.dates || []).sort((a, b) => b.localeCompare(a));
        let prevDaySnapshots = [];
        if (dates.length > 0) {
          const prevRes = await fetch(`${API_BASE}/api/index-tracker/${indexName}/?date=${dates[0]}`).then(r => r.json());
          prevDaySnapshots = prevRes.snapshots || [];
        }
        if (!cancelled) setOhlc(deriveOHLC(todaySnapshots, prevDaySnapshots));
      } catch (err) {
        console.error('OHLC fetch error:', err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    const interval = setInterval(load, 60000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [indexName]);

  if (loading) {
    return <div className="h-16 rounded-lg bg-slate-900/30 animate-pulse" />;
  }
  if (!ohlc) {
    return null;
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
      {[
        ['Open', ohlc.open],
        ['High', ohlc.high],
        ['Low', ohlc.low],
        ['Prev Close', ohlc.prevClose],
      ].map(([label, value]) => (
        <div key={label} className="bg-slate-900/40 rounded-lg p-2 text-center">
          <p className="text-[9px] text-slate-500 uppercase tracking-wider">{label}</p>
          <p className="text-sm font-bold text-white tabular-nums">{fmt(value)}</p>
        </div>
      ))}
    </div>
  );
}
