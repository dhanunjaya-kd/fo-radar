import { useState, useEffect } from 'react';
import { fyersSocket } from './services/fyersSocket';
import api from './services/api';
import MarketBanner from './components/MarketBanner';
import SignalList from './components/SignalList';
import Watchlist from './components/Watchlist';
import Analytics from './components/Analytics';
import IndexTracker from './components/IndexTracker';
import CrudeOilTracker from './components/CrudeOilTracker';
import BullionTracker from './components/BullionTracker';
import NewsFeed from './components/NewsFeed';
import FundamentalsWatchlist from './components/FundamentalsWatchlist';

// The 8 valid tab ids -- used to validate whatever's in localStorage
// so a stale/unrecognized value (e.g. from an older version of the
// app) can't leave activeTab pointing at nothing and rendering blank.
const VALID_TABS = ['signals', 'watchlist', 'oi', 'index', 'crude', 'bullion', 'news', 'value'];

export default function App() {
  const [activeTab, setActiveTab] = useState(() => {
    try {
      const stored = localStorage.getItem('fo-radar-active-tab');
      return VALID_TABS.includes(stored) ? stored : 'signals';
    } catch {
      return 'signals'; // localStorage unavailable (private browsing etc.) -- just use the default
    }
  });
  const [signalCount, setSignalCount] = useState(null);
  const [watchlistCount, setWatchlistCount] = useState(null);

  // Remember whichever tab is active so a page reload stays put instead
  // of always resetting to Live Signals -- the tab itself was never
  // persisted anywhere before this, only held in memory.
  useEffect(() => {
    try {
      localStorage.setItem('fo-radar-active-tab', activeTab);
    } catch {
      // private browsing or similar -- not worth failing over, just skip persisting
    }
  }, [activeTab]);

  const tabs = [
    { id: 'signals', label: 'Live Signals', count: signalCount },
    { id: 'watchlist', label: 'Watchlist', count: watchlistCount },
    { id: 'oi', label: 'OI Analytics', count: null },
    { id: 'index', label: 'Index Tracker', count: null },
    { id: 'crude', label: 'Crude Oil', count: null },
    { id: 'bullion', label: 'Gold & Silver', count: null },
    { id: 'news', label: 'News', count: null },
    { id: 'value', label: 'Value Watchlist', count: null },
  ];

  useEffect(() => {
    // These badges used to be hardcoded (6 and 1) regardless of how many
    // signals actually existed. Poll the same live endpoint the tabs
    // themselves use.
    let cancelled = false;
    const loadCounts = () => {
      api.getSignals?.().then((res) => {
        if (cancelled || !res) return;
        const list = Array.isArray(res) ? res : (res.signals || []);
        setSignalCount(list.length);
        setWatchlistCount(list.filter(s => s.action === 'BUY').length);
      }).catch(() => {});
    };
    loadCounts();
    const interval = setInterval(loadCounts, 15000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  useEffect(() => {
    let cancelled = false;

    // fyersSocket.js reads its token from localStorage, but nothing ever
    // put one there -- it could open the WebSocket but never actually
    // authenticate, so live ticks never arrived. Fetch it from the
    // backend (which already has it, via whichever auth script you last
    // ran) and stash it before connecting.
    const primeTokenAndConnect = async () => {
      try {
        const res = await api.getFyersBrowserToken();
        if (!cancelled && res?.authenticated && res.access_token) {
          localStorage.setItem('fyers_access_token', res.access_token);
          localStorage.setItem('fyers_app_id', res.app_id);
        }
      } catch (e) {
        console.warn('Could not fetch Fyers token for live ticks:', e.message);
      }
      if (!cancelled) fyersSocket.connect();
    };

    primeTokenAndConnect();
    return () => fyersSocket.disconnect();
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      {/* Top Section */}
      <div className="px-4 pt-4 pb-2">
        <MarketBanner />
      </div>

      {/* Tabs */}
      <div className="px-4 mb-4">
        <div className="flex gap-1 bg-slate-900/50 p-1 rounded-xl w-fit">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                activeTab === tab.id
                  ? 'bg-slate-700 text-white shadow-lg'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
              }`}
            >
              {tab.id === 'signals' && '⚡'}
              {tab.id === 'watchlist' && '👁'}
              {tab.id === 'oi' && '📊'}
              {tab.id === 'index' && '📈'}
              {tab.id === 'crude' && '🛢️'}
              {tab.id === 'bullion' && '🥇'}
              {tab.id === 'news' && '📰'}
              {tab.id === 'value' && '💎'}
              {tab.label}
              {tab.count !== null && (
                <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                  activeTab === tab.id ? 'bg-blue-500 text-white' : 'bg-slate-700 text-slate-300'
                }`}>
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Content Area — ONLY ONE TAB VISIBLE */}
      <div className="px-4 pb-8">
        {activeTab === 'signals' && <SignalList />}
        {activeTab === 'watchlist' && <Watchlist />}
        {activeTab === 'oi' && <Analytics />}
        {activeTab === 'index' && <IndexTracker />}
        {activeTab === 'crude' && <CrudeOilTracker />}
        {activeTab === 'bullion' && <BullionTracker />}
        {activeTab === 'news' && <NewsFeed />}
        {activeTab === 'value' && <FundamentalsWatchlist />}
      </div>
    </div>
  );
}