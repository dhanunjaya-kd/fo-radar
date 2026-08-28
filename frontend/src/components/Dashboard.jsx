import SectorPerformance from './SectorPerformance';
import TopLiveSignals from './TopLiveSignals';
import MarketSentimentGauge from './MarketSentimentGauge';

// Aug 28 2026: new Dashboard tab -- the home for the Dashboard-specific
// panels from the 12-screen redesign reference (Sector Performance,
// Top Live Signals, and the Market Sentiment gauge now; Options
// Overview to follow). The global top banner (NIFTY/BANKNIFTY/VIX/
// PCR/Crude + Breadth) deliberately stays OUTSIDE this component --
// it's already shared across every tab via MarketBanner/MarketBreadth
// in App.jsx, so it isn't duplicated here.
//
// onNavigate: passed down from App.jsx (its setActiveTab) so panels
// like Top Live Signals' "View All" button can actually switch to the
// real Live Signals tab, not just be a dead link.
export default function Dashboard({ onNavigate }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <TopLiveSignals onViewAll={onNavigate ? () => onNavigate('signals') : null} />
        </div>
        <MarketSentimentGauge />
      </div>
      <SectorPerformance />
      {/* Options Overview -- added here once built, same
          one-panel-at-a-time approach as everything else in this
          project. */}
    </div>
  );
}
