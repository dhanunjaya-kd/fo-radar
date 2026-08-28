import SectorPerformance from './SectorPerformance';
import TopLiveSignals from './TopLiveSignals';
import MarketSentimentGauge from './MarketSentimentGauge';
import OptionsOverview from './OptionsOverview';
import MarketMovers from './MarketMovers';
import OIDistribution from './OIDistribution';

// Aug 28 2026: new Dashboard tab -- the home for the Dashboard-specific
// panels from the 12-screen redesign reference. Module 1 COMPLETE:
// Top Live Signals, Market Sentiment gauge, Sector Performance, and
// Options Overview -- FII/DII deliberately skipped (no confirmed real
// data source). Market Movers added here too (from Module 6) -- there
// was no natural existing tab for the reduced-scope "Futures/News"
// module (Currency Futures dropped, Index/Stock/Commodity Futures
// already live in existing tabs), so this is where it actually fits.
// OI Distribution (from Module 11 -- turned out to be an OI-by-strike
// chart with a Max Pain marker, not the user-configurable alert-rules
// system the module NAME originally suggested) added here too, paired
// with Options Overview since they cover the same NIFTY/BANKNIFTY
// option-chain territory. The global top banner (NIFTY/BANKNIFTY/VIX/
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
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <OptionsOverview />
        <OIDistribution />
      </div>
      <SectorPerformance />
      <MarketMovers />
    </div>
  );
}
