import { useState, useEffect } from 'react';
import MarketHeatmap from './MarketHeatmap';

const IconChevronLeft = ({ size = 15 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6"/></svg>);
const IconChevronRight = ({ size = 15 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"/></svg>);

/**
 * Sep 19 2026: Market Heatmap moved out of the Market Overview tab
 * (was inline there, one-tab-only) into its own persistent right-hand
 * rail, visible across every tab -- direct request. Same collapsible
 * pattern as the left Sidebar.jsx (icon-only collapsed state,
 * persisted to localStorage under its own key so collapsing this
 * rail doesn't also collapse the left nav or vice versa).
 *
 * MarketHeatmap itself takes width/height now (previously hardcoded
 * 800x320 for the old wide inline spot) -- reflowed narrower-and-
 * taller here to fit a rail rather than a full-width row. Small
 * sectors get grouped into "Other" at this width (see
 * MarketHeatmap.jsx's own comment) -- verified via a real layout
 * test with realistic sector counts before shipping, not assumed to
 * just work at the new aspect ratio.
 */
export default function HeatmapRail() {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('fo-radar-heatmap-rail-collapsed') === 'true'; } catch { return false; }
  });

  useEffect(() => {
    try { localStorage.setItem('fo-radar-heatmap-rail-collapsed', String(collapsed)); } catch {}
  }, [collapsed]);

  if (collapsed) {
    return (
      <div className="hidden lg:flex flex-col items-center shrink-0 h-screen sticky top-0 border-l border-slate-800/60 bg-slate-950/60 w-[40px] pt-4">
        <button
          onClick={() => setCollapsed(false)}
          title="Show Market Heatmap"
          aria-label="Show Market Heatmap"
          className="flex items-center justify-center w-7 h-7 rounded-md border border-slate-700/60 text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 transition-colors"
        >
          <IconChevronLeft />
        </button>
      </div>
    );
  }

  return (
    <div className="hidden lg:block shrink-0 h-screen sticky top-0 overflow-y-auto border-l border-slate-800/60 bg-slate-950/60 w-[300px] p-3">
      <div className="flex items-center justify-end mb-2">
        <button
          onClick={() => setCollapsed(true)}
          title="Collapse Market Heatmap"
          aria-label="Collapse Market Heatmap"
          className="flex items-center justify-center w-7 h-7 rounded-md border border-slate-700/60 text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 transition-colors"
        >
          <IconChevronRight />
        </button>
      </div>
      <MarketHeatmap width={276} height={680} />
    </div>
  );
}
