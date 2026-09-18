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
function StockHoverCard({ stock, x, y, containerWidth }) {
  if (!stock) return null;
  const cardWidth = 390;
  const left = Math.min(Math.max(x + 14, 8), Math.max(8, containerWidth - cardWidth - 8));
  const top = Math.max(y - 12, 8);

  return (
    <div
      className="absolute z-30 pointer-events-none rounded-xl bg-slate-950/95 border border-slate-700 shadow-2xl px-4 py-3"
      style={{ left: `${left}px`, top: `${top}px`, width: `${cardWidth}px` }}
    >
      <div className="flex items-start gap-3">
        <div className="h-9 w-9 shrink-0 rounded-lg bg-slate-100 flex items-center justify-center text-slate-900 font-black text-xs">
          {stock.symbol?.slice(0, 2) || '•'}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-bold text-white">{stock.symbol}</div>
          <div className="text-xs text-slate-400 truncate">{stock.name || stock.symbol}</div>
          <div className="text-[11px] text-slate-500">{stock.sector || ''}</div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-4 gap-2 border-t border-slate-800 pt-3">
        <div>
          <div className="text-[9px] uppercase tracking-wide text-slate-500">Price</div>
          <div className="text-xs font-semibold text-white tabular-nums">{fmtPrice(stock.price)}</div>
        </div>
        <div>
          <div className="text-[9px] uppercase tracking-wide text-slate-500">Changed</div>
          <div className={`text-xs font-semibold tabular-nums ${(stock.change_percent || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {fmtPct(stock.change_percent)}
          </div>
        </div>
        <div>
          <div className="text-[9px] uppercase tracking-wide text-slate-500">OI Buildup</div>
          <div className={`text-[10px] font-semibold leading-tight ${buildupStyle(stock.oi_buildup)}`}>
            {stock.oi_buildup || '—'}
          </div>
        </div>
        <div>
          <div className="text-[9px] uppercase tracking-wide text-slate-500">PCR</div>
          <div className="text-xs font-semibold text-slate-200 tabular-nums">
            {stock.pcr != null ? Number(stock.pcr).toFixed(2) : '—'}
          </div>
        </div>
      </div>

      <div className="mt-2 text-[10px] text-slate-500">
        Volume: {stock.volume != null ? Number(stock.volume).toLocaleString('en-IN') : '—'}
      </div>
    </div>
  );
}

function StockDrilldown({ sector, onBack }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hoveredStock, setHoveredStock] = useState(null);
  const [hoverPos, setHoverPos] = useState({ x: 0, y: 0 });
  const [containerWidth, setContainerWidth] = useState(800);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);

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

  if (loading) {
    return (
      <div className="py-10 text-center text-slate-500 text-sm">
        Fetching live OI for {sector} stocks — this can take a few seconds…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="flex items-center justify-between">
          <button onClick={onBack} className="rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-xs text-slate-300 hover:text-white">
            ← All Sectors
          </button>
          <span className="text-sm text-rose-400">⚠ {error}</span>
        </div>
      </div>
    );
  }

  const stocks = data?.stocks || [];
  if (stocks.length === 0) {
    return (
      <div className="p-6 text-center">
        <button onClick={onBack} className="mb-4 rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-xs text-slate-300 hover:text-white">
          ← All Sectors
        </button>
        <div className="text-sm text-slate-500">No F&O stocks found in this sector.</div>
      </div>
    );
  }

  const WIDTH = 800;
  const HEIGHT = 360;
  const items = stocks.map(s => ({
    ...s,
    name: s.symbol,
    value: 1,
    changePercent: Number(s.change_percent) || 0,
  }));
  const maxAbsChange = Math.max(0.1, ...items.map(i => Math.abs(i.changePercent)));
  const layout = treemapLayout(items, 0, 0, WIDTH, HEIGHT);

  return (
    <div className="relative">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/40">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-xs text-slate-300 hover:text-white hover:border-slate-600"
          >
            ← All Sectors
          </button>
          <div>
            <h3 className="text-sm font-bold text-white">{sector}</h3>
            <p className="text-[10px] text-slate-500">{stocks.length} F&amp;O stocks</p>
          </div>
        </div>
        <div className="text-[10px] text-slate-500">Hover a stock for Price • Chg% • OI Buildup • PCR</div>
      </div>

      {!data?.authenticated && (
        <div className="mx-3 mt-3 text-xs text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
          ⚠ Not authenticated with Fyers right now — showing price/change only, OI buildup and PCR unavailable.
        </div>
      )}

      <div
        className="relative p-3"
        onMouseLeave={() => setHoveredStock(null)}
      >
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full h-auto" style={{ maxHeight: 380 }}>
          {layout.map(tile => {
            const fontSize = Math.min(18, Math.max(9, Math.min(tile.width, tile.height) / 7));
            const showPct = tile.width > 42 && tile.height > 30;
            return (
              <g
                key={tile.symbol}
                className="cursor-default"
                onMouseEnter={e => {
                  setHoveredStock(tile);
                  const host = e.currentTarget.ownerSVGElement.parentElement;
                  const rect = host.getBoundingClientRect();
                  setContainerWidth(rect.width);
                  setHoverPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
                }}
                onMouseMove={e => {
                  const host = e.currentTarget.ownerSVGElement.parentElement;
                  const rect = host.getBoundingClientRect();
                  setContainerWidth(rect.width);
                  setHoverPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
                }}
              >
                <rect
                  x={tile.x}
                  y={tile.y}
                  width={tile.width}
                  height={tile.height}
                  fill={colorForChange(tile.changePercent, maxAbsChange)}
                  stroke="#0f172a"
                  strokeWidth="2"
                  rx="2"
                />
                {tile.width > 28 && tile.height > 18 && (
                  <text
                    x={tile.x + tile.width / 2}
                    y={tile.y + tile.height / 2 - (showPct ? 7 : 0)}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fill="#fff"
                    fontSize={fontSize}
                    fontWeight="700"
                  >
                    {tile.symbol}
                  </text>
                )}
                {showPct && (
                  <text
                    x={tile.x + tile.width / 2}
                    y={tile.y + tile.height / 2 + 10}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fill="#fff"
                    fontSize={Math.max(8, fontSize * 0.68)}
                    opacity="0.9"
                  >
                    {fmtPct(tile.changePercent)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        <StockHoverCard
          stock={hoveredStock}
          x={hoverPos.x}
          y={hoverPos.y}
          containerWidth={containerWidth}
        />
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
        <p className="text-[10px] text-slate-500 mt-0.5">
          Tile size = number of F&amp;O stocks in that sector, color = today's average change% — click a sector to drill into stocks
        </p>
      </div>

      {!selectedSector && (
        <div className="p-3">
          <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full h-auto" style={{ maxHeight: 340 }}>
            {layout.map((tile) => {
              const fontSize = Math.min(16, Math.max(9, Math.min(tile.width, tile.height) / 8));
              const showDetail = tile.width > 60 && tile.height > 36;
              return (
                <g
                  key={tile.name}
                  onClick={() => setSelectedSector(tile.name)}
                  className="cursor-pointer transition-opacity hover:opacity-80"
                >
                  <rect
                    x={tile.x}
                    y={tile.y}
                    width={tile.width}
                    height={tile.height}
                    fill={colorForChange(tile.changePercent, maxAbsChange)}
                    stroke="#0f172a"
                    strokeWidth="2"
                  />
                  {tile.width > 30 && tile.height > 20 && (
                    <text
                      x={tile.x + tile.width / 2}
                      y={tile.y + tile.height / 2 - (showDetail ? 6 : 0)}
                      textAnchor="middle"
                      dominantBaseline="middle"
                      fill="#fff"
                      fontSize={fontSize}
                      fontWeight="700"
                    >
                      {tile.name}
                    </text>
                  )}
                  {showDetail && (
                    <text
                      x={tile.x + tile.width / 2}
                      y={tile.y + tile.height / 2 + 12}
                      textAnchor="middle"
                      dominantBaseline="middle"
                      fill="#fff"
                      fontSize={Math.max(9, fontSize * 0.7)}
                      opacity="0.9"
                    >
                      {tile.changePercent >= 0 ? '+' : ''}{tile.changePercent.toFixed(2)}%
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        </div>
      )}

      {selectedSector && (
        <StockDrilldown
          sector={selectedSector}
          onBack={() => setSelectedSector(null)}
        />
      )}
    </div>
  );
}
