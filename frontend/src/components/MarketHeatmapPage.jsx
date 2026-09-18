import MarketHeatmap from './MarketHeatmap';

/**
 * Dedicated Market Heatmap page.
 * Reuses the existing heatmap implementation and data flow unchanged.
 */
export default function MarketHeatmapPage() {
  return (
    <div className="space-y-4">
      <MarketHeatmap />
    </div>
  );
}
