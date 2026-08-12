import { useEffect, useState } from 'react';

// Relative on purpose -- see the same note in SignalList.jsx / IndexTracker.jsx.
const API_BASE = import.meta.env.VITE_API_URL || '';

export default function NewsFeed() {
  const [news, setNews] = useState([]);
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

  if (loading && news.length === 0) {
    return <div className="p-10 text-center text-slate-500 text-sm">Loading news...</div>;
  }
  if (error) {
    return <div className="p-10 text-center text-slate-500 text-sm">Couldn't load news: {error}</div>;
  }
  if (news.length === 0) {
    return (
      <div className="p-10 text-center text-slate-500 text-sm max-w-md mx-auto">
        No F&O-relevant headlines right now. This only shows stories that directly mention one of your F&O tickers by name — quiet periods are expected, not a bug. Some real news can still be missed if a headline uses a full company name instead of the bare ticker.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="bg-indigo-500/10 border border-indigo-500/20 rounded-lg px-4 py-2.5 text-xs text-indigo-300">
        Real headlines from ET's Markets/Stocks/Company RSS feeds, filtered to stories that directly mention
        an F&O ticker. Refreshes every 5 minutes. Known gap: only matches the bare ticker in text, not full
        company names — some relevant stories can still be missed.
      </div>
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
    </div>
  );
}
