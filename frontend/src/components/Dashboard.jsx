import SectorPerformance from './SectorPerformance';
import TopLiveSignals from './TopLiveSignals';

// Aug 28 2026: new Dashboard tab -- the home for the Dashboard-specific
// panels from the 12-screen redesign reference (Sector Performance and
// Top Live Signals now, Market Sentiment gauge / Options Overview to
// follow). The global top banner (NIFTY/BANKNIFTY/VIX/PCR/Crude +
// Breadth) deliberately stays OUTSIDE this component -- it's already
// shared across every tab via MarketBanner/MarketBreadth in App.jsx,
// so it isn't duplicated here.
//
// onNavigate: passed down from App.jsx (its setActiveTab) so panels
// like Top Live Signals' "View All" button can actually switch to the
// real Live Signals tab, not just be a dead link.
export default function Dashboard({ onNavigate }) {
  return (
    <div className="space-y-4">
      <TopLiveSignals onViewAll={onNavigate ? () => onNavigate('signals') : null} />
      <SectorPerformance />
      {/* Market Sentiment gauge, Options Overview -- added here as each
          is built, same one-panel-at-a-time approach as everything else
          in this project. */}
    </div>
  );
}
