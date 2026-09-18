import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Aug 28 2026: layout math verified in test_treemap_layout.js before
// this component was written -- no overlaps, exact area coverage,
// proportional sizing, all confirmed independently of the JSX.
function treemapLayout(items, x, y, width, height, direction = 'horizontal') {
  if (items.length === 0) return [];
  if (items.length === 1) {
    return [{ ...items[0], x, y, width, height }];
  }
  const totalValue = items.reduce((sum, item) => sum + item.value, 0);
  let cumSum = 0;
  let splitIndex = 1;
  const targetHalf = totalValue / 2;
  for (let i = 0; i < items.length; i++) {
    cumSum += items[i].value;
    if (cumSum >= targetHalf) { splitIndex = i + 1; break; }
  }
  splitIndex = Math.max(1, Math.min(splitIndex, items.length - 1));
  const groupA = items.slice(0, splitIndex);
  const groupB = items.slice(splitIndex);
  const valueA = groupA.reduce((sum, item) => sum + item.value, 0);
  const ratioA = valueA / totalValue;
  if (direction === 'horizontal') {
    const widthA = width * ratioA;
    return [
      ...treemapLayout(groupA, x, y, widthA, height, 'vertical'),
      ...treemapLayout(groupB, x + widthA, y, width - widthA, height, 'vertical'),
    ];
  } else {
    const heightA = height * ratioA;
    return [
      ...treemapLayout(groupA, x, y, width, heightA, 'horizontal'),
      ...treemapLayout(groupB, x, y + heightA, width, height - heightA, 'horizontal'),
    ];
  }
}

// Aug 28 2026: color scaled to the DAY'S real spread across sectors
// (same "scale to what actually happened today" principle used for
// Sector Performance's bars and the volume formatter) rather than a
// fixed +-5% assumption that would make a quiet day look uniformly
// gray and a wild day clip to solid colors everywhere.
function colorForChange(changePercent, maxAbs) {
  const intensity = Math.min(1, Math.abs(changePercent) / Math.max(maxAbs, 0.1));
  if (changePercent >= 0) {
    // emerald-500 at full intensity, fading toward slate-800 at zero
    const g = Math.round(30 + intensity * 100);
    return `rgba(16, ${129 + Math.round(intensity * 30)}, 90, ${0.25 + intensity * 0.55})`;
  }
  return `rgba(244, 63, 94, ${0.25 + intensity * 0.55})`;
}

function fmtPrice(n) {
  if (n === null || n === undefined || isNaN(n)) return '—';
  return `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}
function fmtPct(n) {
  if (n === null || n === undefined || isNaN(n)) return '—';
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}
function buildupStyle(buildup) {
  if (!buildup) return 'text-slate-500';
  if (buildup.includes('PE writing')) return 'text-emerald-400';
  if (buildup.includes('CE writing')) return 'text-rose-400';
  return 'text-slate-300';
}

// Aug 30 2026: sector click-through. Fetches /api/sector-stocks/<sector>/
// on open -- a LIVE OI fetch per stock in the sector on the backend
// (see SectorStocksView in views.py for why this is deliberately live
// rather than reused from the main scan's already-filtered signal
// data). Expect a few seconds' wait, not an instant response -- that
// tradeoff was chosen directly over an instant-but-mostly-blank
// version.
function SectorDrawer({ sector, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/api/sector-stocks/${encodeURIComponent(sector)}/`)
      .then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(json => { if (!cancelled) setData(json); })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [sector]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <div
        className="w-full max-w-2xl max-h-[80vh] overflow-hidden rounded-xl bg-slate-900 border border-slate-700 flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
          <h3 className="text-sm font-bold text-white">{sector} — stocks</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-lg leading-none px-2">×</button>
        </div>
        <div className="overflow-y-auto p-4">
          {loading && (
            <div className="py-8 text-center text-slate-500 text-sm">
              Fetching live OI for {sector} stocks — this can take a few seconds…
            </div>
          )}
          {error && <div className="py-4 text-center text-rose-400 text-sm">⚠ {error}</div>}
          {!loading && !error && data && data.stocks.length === 0 && (
            <div className="py-8 text-center text-slate-500 text-sm">No F&O stocks found in this sector.</div>
          )}
          {!loading && !error && data && data.stocks.length > 0 && (
            <>
              {!data.authenticated && (
                <div className="mb-3 text-xs text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
                  ⚠ Not authenticated with Fyers right now — showing price/change only, OI buildup unavailable.
                </div>
              )}
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-slate-500 border-b border-slate-800">
                    <th className="text-left px-2 py-2 font-medium">Symbol</th>
                    <th className="text-right px-2 py-2 font-medium">Price</th>
                    <th className="text-right px-2 py-2 font-medium">Chg%</th>
                    <th className="text-left px-2 py-2 font-medium">OI Buildup</th>
                    <th className="text-right px-2 py-2 font-medium">PCR</th>
                  </tr>
                </thead>
                <tbody>
                  {data.stocks.map(s => (
                    <tr key={s.symbol} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="px-2 py-2 text-white font-medium whitespace-nowrap">{s.symbol}</td>
                      <td className="px-2 py-2 text-right text-slate-300 tabular-nums">{fmtPrice(s.price)}</td>
                      <td className={`px-2 py-2 text-right tabular-nums ${(s.change_percent || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {fmtPct(s.change_percent)}
                      </td>
                      <td className={`px-2 py-2 whitespace-nowrap ${buildupStyle(s.oi_buildup)}`}>{s.oi_buildup || '—'}</td>
                      <td className="px-2 py-2 text-right text-slate-300 tabular-nums">{s.pcr != null ? s.pcr.toFixed(2) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function MarketHeatmap() {
  const [sectors, setSectors] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedSector, setSelectedSector] = useState(null);

  useEffect(() => {
    let mounted = true;
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/market-summary/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (mounted) setSectors(json.sectors || []);
      } catch (err) {
        console.error('Market heatmap fetch error:', err);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  if (loading) {
    return <div className="h-72 rounded-xl bg-slate-800/30 animate-pulse border border-slate-700/30" />;
  }
  if (!sectors || sectors.length === 0) {
    return (
      <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-6 text-center">
        <p className="text-sm text-slate-500">No sector data yet -- waiting for the first scan cycle.</p>
      </div>
    );
  }

  const WIDTH = 800, HEIGHT = 320;
  // Sized by real stock count per sector (how many of your F&O stocks
  // fall in that sector) -- NOT market cap, since that's not
  // available here. A sector with more listed F&O stocks gets a
  // bigger tile; this is an honest, real basis for size, just a
  // different one than the mockup's imagined market-cap weighting.
  const items = sectors
    .filter(s => s.stock_count > 0)
    .map(s => ({ name: s.sector, value: s.stock_count, changePercent: s.change_percent, stockCount: s.stock_count }))
    .sort((a, b) => b.value - a.value);
  const maxAbsChange = Math.max(0.1, ...items.map(i => Math.abs(i.changePercent)));
  const layout = treemapLayout(items, 0, 0, WIDTH, HEIGHT);

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-700/40">
        <h3 className="text-sm font-bold text-white">Market Heatmap</h3>
        <p className="text-[10px] text-slate-500 mt-0.5">Tile size = number of F&O stocks in that sector, color = today's average change% — click a sector to see its stocks</p>
      </div>
      <div className="p-3">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full h-auto" style={{ maxHeight: 340 }}>
          {layout.map((tile) => {
            const fontSize = Math.min(16, Math.max(9, Math.min(tile.width, tile.height) / 8));
            const showDetail = tile.width > 60 && tile.height > 36;
            return (
              <g key={tile.name} onClick={() => setSelectedSector(tile.name)} className="cursor-pointer transition-opacity hover:opacity-80">
                <rect
                  x={tile.x} y={tile.y} width={tile.width} height={tile.height}
                  fill={colorForChange(tile.changePercent, maxAbsChange)}
                  stroke="#0f172a" strokeWidth="2"
                />
                {tile.width > 30 && tile.height > 20 && (
                  <text x={tile.x + tile.width / 2} y={tile.y + tile.height / 2 - (showDetail ? 6 : 0)}
                    textAnchor="middle" dominantBaseline="middle" fill="#fff" fontSize={fontSize} fontWeight="700">
                    {tile.name}
                  </text>
                )}
                {showDetail && (
                  <text x={tile.x + tile.width / 2} y={tile.y + tile.height / 2 + 12}
                    textAnchor="middle" dominantBaseline="middle" fill="#fff" fontSize={Math.max(9, fontSize * 0.7)} opacity="0.9">
                    {tile.changePercent >= 0 ? '+' : ''}{tile.changePercent.toFixed(2)}%
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      {selectedSector && (
        <SectorDrawer sector={selectedSector} onClose={() => setSelectedSector(null)} />
      )}
    </div>
  );
}
