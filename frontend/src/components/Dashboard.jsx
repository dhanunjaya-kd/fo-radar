import SectorPerformance from './SectorPerformance';

// Aug 28 2026: new Dashboard tab -- the home for the Dashboard-specific
// panels from the 12-screen redesign reference (Sector Performance now,
// Market Sentiment gauge / Top Live Signals / Options Overview to
// follow). The global top banner (NIFTY/BANKNIFTY/VIX/PCR/Crude +
// Breadth) deliberately stays OUTSIDE this component -- it's already
// shared across every tab via MarketBanner/MarketBreadth in App.jsx,
// so it isn't duplicated here.
export default function Dashboard() {
  return (
    <div className="space-y-4">
      <SectorPerformance />
      {/* Market Sentiment gauge, Top Live Signals, Options Overview --
          added here as each is built, same one-panel-at-a-time approach
          as everything else in this project. */}
    </div>
  );
}
