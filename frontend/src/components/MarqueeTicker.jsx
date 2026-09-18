import { useState, useEffect } from 'react';
import './MarqueeTicker.css';

const API_BASE = import.meta.env.VITE_API_URL || '';

/**
 * Sep 18 2026: complete rewrite. The previous version was never wired
 * into App.jsx (confirmed: zero imports anywhere in the app) and had
 * two real bugs that would have surfaced the moment anyone tried to
 * use it -- a hardcoded http://127.0.0.1:8000 URL (breaks on any real
 * deployment, inconsistent with every other component's API_BASE
 * pattern) and JSX class names (.marquee-container/.marquee-content)
 * that didn't match what MarqueeTicker.css actually defines
 * (.marquee-wrapper/.marquee-track) -- so even running locally, none
 * of the scroll animation or styling would have applied.
 *
 * Data source: /api/stocks/fo-list/ (FoStockListOldView) -- reused
 * as-is, no backend change needed. It already reads the same live,
 * already-populated _stock_cache the Sniper engine itself uses, so
 * this costs zero new Fyers calls -- purely a new reader of data
 * that's already flowing every scan cycle.
 *
 * Gap% is NOT a stored field anywhere in the backend -- computed here
 * from fields _stock_cache already has (open, price, change_percent):
 * prevClose = price / (1 + change_percent/100), gap% = (open -
 * prevClose) / prevClose * 100. Standard definition (today's open vs
 * yesterday's close), not invented.
 *
 * Filtered to real gap movers (|gap%| >= GAP_THRESHOLD), not all 208
 * stocks -- matches the reference's own apparent behavior (every
 * visible entry has a notable gap badge, not a wall of ~0% noise).
 *
 * Sep 18 2026: FIXED a real bug found live -- the ticker was
 * rendering nothing at all on an ordinary trading day. Root cause
 * verified directly, not guessed: confirmed there is no market-hours
 * gate anywhere in this chain (FoStockListOldView reads _stock_cache
 * unconditionally, and _stock_cache itself is only ever initialized
 * to {} once at module load -- never cleared on market close, so it
 * holds real data even after hours). The actual cause was this
 * threshold itself: 1.0% was too strict for a normal day's actual
 * gap distribution across 207 stocks, so the filter legitimately
 * matched zero -- not broken, just tuned wrong, with no fallback for
 * that case. Lowered to 0.3% (most trading days have real movement at
 * this scale), and backstopped with a genuine fallback below: if
 * *even that* still matches nothing, the ticker shows top movers by
 * plain change% instead of going empty -- an empty scrolling strip is
 * worse than one showing smaller moves, since it looks broken either
 * way to someone watching the screen.
 */
const GAP_THRESHOLD = 0.3;
const MAX_TICKER_ITEMS = 30;

const MarqueeTicker = () => {
  const [items, setItems] = useState([]);
  const [signalCount, setSignalCount] = useState(null);
  const [marketOpen, setMarketOpen] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/stocks/fo-list/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        const stocks = json.stocks || [];
        if (!cancelled) setMarketOpen(json.market_open ?? null);

        const scored = stocks
          .map(s => {
            const price = s.price;
            const open = s.open;
            const changePct = s.change_percent;
            if (price == null || open == null || changePct == null) return null;
            const prevClose = price / (1 + changePct / 100);
            if (!prevClose) return null;
            const gapPct = ((open - prevClose) / prevClose) * 100;
            return { symbol: s.symbol, price, changePct, gapPct };
          })
          .filter(Boolean);

        let withGap = scored
          .filter(s => Math.abs(s.gapPct) >= GAP_THRESHOLD)
          .sort((a, b) => Math.abs(b.gapPct) - Math.abs(a.gapPct))
          .slice(0, MAX_TICKER_ITEMS);

        // Fallback: even 0.3% can legitimately match nothing on a very
        // flat day. Rather than render nothing, fall back to the
        // biggest plain movers by change% -- still real, still live,
        // just not framed as a "gap" specifically.
        if (withGap.length === 0) {
          withGap = scored
            .slice()
            .sort((a, b) => Math.abs(b.changePct) - Math.abs(a.changePct))
            .slice(0, MAX_TICKER_ITEMS);
        }

        if (!cancelled) setItems(withGap);
      } catch (err) {
        console.error('Ticker fetch error:', err);
      }
    };

    const loadSignalCount = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/sniper-only/`);
        if (!res.ok) return;
        const json = await res.json();
        const list = Array.isArray(json) ? json : (json.signals || []);
        if (!cancelled) setSignalCount(list.length);
      } catch {
        // Signal count is decorative on this strip -- a failed fetch
        // just means the badge doesn't render, not an error state.
      }
    };

    load();
    loadSignalCount();
    const interval = setInterval(() => { load(); loadSignalCount(); }, 30000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  if (items.length === 0) {
    // Sep 19 2026: was a silent `return null` regardless of why --
    // indistinguishable from a real bug. When the backend's own
    // is_market_hours() says the market is genuinely closed, that IS
    // the honest reading (in-memory quote cache has nothing to show,
    // by design, until next open) -- say so instead of just vanishing.
    // Still returns null for the rare during-hours-and-truly-empty
    // case (both the gap filter and the plain-movers fallback found
    // nothing) -- that's a real, if unlikely, "nothing to report"
    // state, not a closed-market one.
    if (marketOpen === false) {
      return (
        <div className="marquee-wrapper">
          <div className="ticker-item" style={{ padding: '6px 16px', opacity: 0.6 }}>
            Market closed — ticker resumes at next session
          </div>
        </div>
      );
    }
    return null;
  }

  // Doubled for a seamless loop, same technique the CSS's own
  // scroll-left keyframe (translateX(-33.333%) across a tripled
  // track) already assumed -- tripled here, not just doubled, to
  // match that exact math rather than guessing a different multiple.
  const displayItems = [...items, ...items, ...items];

  return (
    <div className="marquee-wrapper">
      <div className="marquee-track">
        {signalCount !== null && (
          <span className="ticker-item">
            <span className="ticker-signal sniper">Signals {signalCount}</span>
          </span>
        )}
        {displayItems.map((item, i) => {
          const isRealGap = Math.abs(item.gapPct) >= GAP_THRESHOLD;
          return (
            <span key={`${item.symbol}-${i}`} className="ticker-item">
              {isRealGap ? (
                <span className={`ticker-signal ${item.gapPct >= 0 ? 'hold' : 'watchlist'}`}>
                  {item.gapPct >= 0 ? 'GAP UP' : 'GAP DOWN'}
                </span>
              ) : (
                <span className={`ticker-signal ${item.changePct >= 0 ? 'hold' : 'watchlist'}`}>
                  {item.changePct >= 0 ? 'UP' : 'DOWN'}
                </span>
              )}
              <span className="ticker-symbol">{item.symbol}</span>
              <span className="ticker-price">{item.price.toFixed(2)}</span>
              <span className={`ticker-change ${item.changePct >= 0 ? 'up' : 'down'}`}>
                {item.changePct >= 0 ? '+' : ''}{item.changePct.toFixed(2)}%
              </span>
              {isRealGap && (
                <span className={`ticker-gap ${item.gapPct >= 0 ? 'up' : 'down'}`}>
                  {item.gapPct >= 0 ? '+' : ''}{item.gapPct.toFixed(1)}% gap
                </span>
              )}
            </span>
          );
        })}
      </div>
    </div>
  );
};

export default MarqueeTicker;
