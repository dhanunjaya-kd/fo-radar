import TopLiveSignals from './TopLiveSignals';
import MarketSentimentGauge from './MarketSentimentGauge';
import AttentionFeed from './AttentionFeed';
import SectorStrength from './SectorStrength';
import OISnapshot from './OISnapshot';

// Aug 28 2026: REBUILT per direct feedback -- "Dashboard should
// answer in 5 seconds: market direction, strongest signals, OI
// positioning, sector strength, options sentiment, what needs
// attention now. Dashboard = command center. Other tabs =
// investigation tools."
//
// What changed: the FULL-detail widgets that used to live here
// (OIDistribution's complete strike-by-strike bar chart, Options
// Overview's full 4-card+slider+straddle breakdown, the complete
// Sector Performance table, the full Market Movers list) are gone --
// those are genuinely detailed analysis, not a 5-second scan, and
// belong in their own investigation-tool tabs, not here. Replaced
// with concise, condensed versions built specifically for a glance:
// AttentionFeed (new -- resolved-today signals + still-open high-
// conviction ones), SectorStrength (top/bottom 3, not all ~15
// sectors), OISnapshot (PCR + sentiment + Max Pain, 3 numbers, not
// the full options panel).
//
// FII/DII still deliberately absent -- no confirmed real data source,
// unchanged from the original scoping decision.
//
// The global top banner (NIFTY/BANKNIFTY/VIX/PCR/Crude + Breadth)
// stays OUTSIDE this component as before -- shared across every tab
// via MarketBanner/MarketBreadth in App.jsx.
//
// onNavigate: passed down from App.jsx (its setActiveTab) so every
// "View All"/"Details" link here actually jumps to the real
// investigation-tool tab, not a dead link.
export default function Dashboard({ onNavigate }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <TopLiveSignals onViewAll={onNavigate ? () => onNavigate('signals') : null} limit={3} />
        </div>
        <MarketSentimentGauge />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <AttentionFeed onNavigate={onNavigate} />
        <OISnapshot onNavigate={onNavigate} />
      </div>
      <SectorStrength onNavigate={onNavigate} />
    </div>
  );
}
