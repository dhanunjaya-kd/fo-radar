import TopLiveSignals from './TopLiveSignals';
import MarketPulse from './MarketPulse';
import IndexCard from './IndexCard';
import TodaysMovers from './TodaysMovers';
import MarketSentimentGauge from './MarketSentimentGauge';
import OIDistribution from './OIDistribution';
import DataHealthStrip from './DataHealthStrip';
import { TrendMomentumCard } from './IndexTracker';

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
//
// Aug 31 2026: AttentionFeed removed per direct feedback -- it draws
// from the same still-open high-conviction signals as TopLiveSignals,
// so with few active signals both boxes ended up showing the exact
// same rows. Live Signals already has its own full tab for the
// complete list, so two overlapping summaries here was redundancy,
// not two genuinely different views.
// Aug 31 2026 (later same day): DataHealthStrip added at top (Section
// 18 of the UI Corrections checklist) and NoTradeLog takes the grid
// slot AttentionFeed vacated -- genuinely different content this
// time (WHY candidates are being rejected right now, from
// NoTradeLogView/P0-6), not a second view of the same signals.
export default function Dashboard({ onNavigate }) {
  return (
    <div className="space-y-3">
      <DataHealthStrip />
      {/* Sep 18 2026: 4 index cards (sparkline + 18-day range + real
          regime badge), sitting above Market Pulse per the reference
          layout -- kept separate from the existing TrendMomentumCard
          grid below, which shows genuinely different detail
          (RSI/SMA/ATR/pivot levels) this new card intentionally
          keeps compact. Neither replaces the other. */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
        <IndexCard indexName="NIFTY" displayName="NIFTY 50" />
        <IndexCard indexName="BANKNIFTY" displayName="BANK NIFTY" />
        <IndexCard indexName="SENSEX" displayName="SENSEX" />
        <IndexCard indexName="VIX" displayName="INDIA VIX" />
      </div>
      <MarketPulse />
      {/* Sep 2 2026: moved here from Index Tracker per direct request --
          "market direction" is the first thing this file's own header
          comment says the dashboard should answer. Reuses the exact
          same TrendMomentumCard component (now a named export from
          IndexTracker.jsx) rather than a duplicate copy, so a future
          change to the card only has to happen in one place. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <TrendMomentumCard indexName="NIFTY" />
        <TrendMomentumCard indexName="BANKNIFTY" />
      </div>
      {/* Sep 21 2026: OIDistribution moved into this row's side-panel
          column, direct request ("move this to the side panel") --
          this lg:grid-cols-3 split (TopLiveSignals 2/3, narrow column
          1/3) was already the dashboard's one existing "side panel"
          pattern, so OIDistribution joins it here (stacked below the
          gauge) rather than a new, separate side-panel layout
          invented elsewhere on the page. SectorStrength, previously
          full-width below this row, moved to the Market Heatmap tab
          instead (also direct request) -- sector-level detail belongs
          next to the sector-level heatmap view, not the 5-second-
          glance Dashboard; same component, not a duplicate. */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="lg:col-span-2 min-w-0">
          <TopLiveSignals onViewAll={onNavigate ? () => onNavigate('signals') : null} limit={3} />
        </div>
        {/* Sep 21 2026 (later same day): min-w-0 added defensively --
            NOT a confirmed fix. Direct request reported this column
            still rendering full-width after the restructure above, and
            the working hypothesis was OIDistribution's own hardcoded
            `const WIDTH = 700` SVG viewBox forcing the grid track via
            the standard "grid items don't shrink below min-content"
            behavior. Actually tested that hypothesis with a faithful
            Puppeteer reproduction (real header/legend/SVG markup, 1900px
            viewport) rather than assuming it -- min-w-0 made ZERO
            measurable difference in either test; the column narrowed
            correctly (544px, a sane side-panel width) with or without
            it. So the real cause of what was reported is still
            unconfirmed -- most likely a stale Vite/browser cache rather
            than this layout code, given the code itself measures
            correctly in isolation. min-w-0 is harmless and correct
            practice regardless, so left in, but do not treat its
            presence as "the fix" if this gets revisited. */}
        <div className="space-y-3 min-w-0">
          <MarketSentimentGauge />
          <OIDistribution />
        </div>
      </div>
      {/* Sep 3 2026: NoTradeLog + OISnapshot removed per direct request
          ("no use of this 2") -- OISnapshot's PCR/Sentiment/Max Pain
          summary became redundant once the full OIDistribution chart
          landed on the Dashboard too. Neither component file was
          deleted, just no longer rendered here. */}
      <TodaysMovers />
    </div>
  );
}
