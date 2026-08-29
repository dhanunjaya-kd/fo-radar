// Aug 28 2026: extracted from 6 tabs that already, coincidentally,
// used the exact same "bg-indigo-500/10 border border-indigo-500/20
// rounded-lg px-4 py-2.5 text-xs text-indigo-300" markup independently
// (MarketView, IndexTracker, NewsFeed, FundamentalsWatchlist,
// CrudeOilTracker, BullionTracker) -- coincidentally matching classes
// is fragile (one tab's styling could silently drift from the others
// over time); one shared component makes them structurally the same,
// not just accidentally alike right now.
export default function TabInfoBanner({ children, className = '' }) {
  return (
    <div className={`bg-indigo-500/10 border border-indigo-500/20 rounded-lg px-4 py-2.5 text-xs text-indigo-300 ${className}`}>
      {children}
    </div>
  );
}
