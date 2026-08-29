import { useEffect, useState } from 'react';
import TabInfoBanner from './TabInfoBanner';

// Relative on purpose -- see the same note in SignalList.jsx / IndexTracker.jsx.
const API_BASE = import.meta.env.VITE_API_URL || '';

export default function NewsFeed() {
  const [news, setNews] = useState([]);
  const [broadNews, setBroadNews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch(`${API_BASE}/api/news/`)
        .then(r => r.json())
        .then(data => {
          if (cancelled) return;
          setNews(data.news || []);
          setBroadNews(data.broad_news || []);
          setError(null);
        })
        .catch(e => { if (!cancelled) setError(e.message); })
        .finally(() => { if (!cancelled) setLoading(false); });
    };
    load();
    // 5 min, matches the backend's own cache TTL -- polling faster
    // than that wouldn't ever show anything newer.
    const interval = setInterval(load, 300000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  if (loading && news.length === 0 && broadNews.length === 0) {
    return <div className="p-10 text-center text-slate-500 text-sm">Loading news...</div>;
  }
  if (error) {
    return <div className="p-10 text-center text-slate-500 text-sm">Couldn't load news: {error}</div>;
  }
  if (news.length === 0 && broadNews.length === 0) {
    return (
      <div className="p-10 text-center text-slate-500 text-sm max-w-md mx-auto">
        No headlines right now. This is unusual for both feeds to be empty at once — worth a look if it persists.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <TabInfoBanner className="mb-3">
          Real headlines from ET's Markets/Stocks/Company RSS feeds, filtered to stories that directly mention
          an F&O ticker. Refreshes every 5 minutes. Known gap: only matches the bare ticker in text, not full
          company names — some relevant stories can still be missed.
        </TabInfoBanner>
        {news.length === 0 ? (
          <p className="text-sm text-slate-500 px-1">
            No F&O-relevant headlines right now — quiet periods are expected, not a bug.
          </p>
        ) : (
          <div className="space-y-2">
            {news.map((item, i) => (
              <a
                key={item.link || i}
                href={item.link}
                target="_blank"
                rel="noopener noreferrer"
                className="block bg-slate-900/50 border border-slate-800 rounded-xl px-4 py-3 hover:border-slate-700 hover:bg-slate-900/80 transition-colors"
              >
                <p className="text-sm text-white font-medium leading-snug">{item.title}</p>
                <div className="flex items-center gap-2 mt-1.5 text-[11px] text-slate-500">
                  <span className="font-semibold text-slate-400">{item.source}</span>
                  <span>·</span>
                  <span>{item.time}</span>
                </div>
              </a>
            ))}
          </div>
        )}
      </div>

      {/* Aug 28 2026: broader macro/global market news -- the F&O
          ticker filter above deliberately excludes this (bond yields,
          Fed decisions, global market moves rarely name a specific
          stock). Kept as its own clearly-labeled section rather than
          merged into the list above -- reading a "Japan tech shares
          rally" headline in what's supposed to be an F&O-ticker feed
          would be confusing without this separation. Same
          /api/news/ response, no extra request. */}
      {broadNews.length > 0 && (
        <div>
          <div className="bg-purple-500/10 border border-purple-500/20 rounded-lg px-4 py-2.5 text-xs text-purple-300 mb-3">
            Broader market news — same ET feeds, not filtered to a specific ticker. Covers macro moves
            (yields, global markets, policy) that the F&O-specific feed above intentionally excludes.
          </div>
          <div className="space-y-2">
            {broadNews.map((item, i) => (
              <a
                key={item.link || i}
                href={item.link}
                target="_blank"
                rel="noopener noreferrer"
                className="block bg-slate-900/50 border border-slate-800 rounded-xl px-4 py-3 hover:border-slate-700 hover:bg-slate-900/80 transition-colors"
              >
                <p className="text-sm text-white font-medium leading-snug">{item.title}</p>
                <div className="flex items-center gap-2 mt-1.5 text-[11px] text-slate-500">
                  <span className="font-semibold text-slate-400">{item.source}</span>
                  <span>·</span>
                  <span>{item.time}</span>
                </div>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
