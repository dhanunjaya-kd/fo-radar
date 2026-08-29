import { useState, useEffect } from 'react';
import { fyersSocket } from './services/fyersSocket';
import api from './services/api';
import { ThemeProvider, useTheme } from './components/ThemeContext';
import ThemeToggle from './components/ThemeToggle';
import './components/theme-overrides.css';
import './components/density-overrides.css';
import MarketBanner from './components/MarketBanner';
import MarketBreadth from './components/MarketBreadth';
import SignalList from './components/SignalList';
import Analytics from './components/Analytics';
import IndexTracker from './components/IndexTracker';
import MarketView from './components/MarketView';
import CrudeOilTracker from './components/CrudeOilTracker';
import BullionTracker from './components/BullionTracker';
import NewsFeed from './components/NewsFeed';
import FundamentalsWatchlist from './components/FundamentalsWatchlist';
import DailyBacktestTab from './components/DailyBacktestTab';
import Dashboard from './components/Dashboard';
import SettingsPanel from './components/SettingsPanel';
import StrategyBacktest from './components/StrategyBacktest';

// Aug 28 2026: lifted verbatim from SignalList.jsx (top-nav redesign --
// the alert bell moved here). Duplicated rather than pulled into a new
// shared-icons file, matching this project's existing preference for
// a few duplicated lines over a riskier shared-dependency refactor.
const IconBell = ({ size = 16 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
);
const IconBellOff = ({ size = 16 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M13.73 21a2 2 0 0 1-3.46 0"/><path d="M18.63 13A17.89 17.89 0 0 1 18 8"/><path d="M6.26 6.26A5.86 5.86 0 0 0 6 8c0 7-3 9-3 9h14"/><path d="M18 8a6 6 0 0 0-9.33-5"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
);
const IconMaximize = ({ size = 17 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
);

// The 11 valid tab ids -- used to validate whatever's in localStorage
// so a stale/unrecognized value (e.g. from an older version of the
// app) can't leave activeTab pointing at nothing and rendering blank.
// Aug 28 2026: added 'dashboard' -- new home tab for the Dashboard-
// specific panels from the 12-screen redesign reference (Sector
// Performance now, more to follow).
const VALID_TABS = ['dashboard', 'signals', 'oi', 'index', 'market', 'crude', 'bullion', 'news', 'value', 'backtest', 'settings', 'strategy'];

function AppShell() {
  const { theme } = useTheme();
  const [activeTab, setActiveTab] = useState(() => {
    try {
      const stored = localStorage.getItem('fo-radar-active-tab');
      return VALID_TABS.includes(stored) ? stored : 'signals';
    } catch {
      return 'signals'; // localStorage unavailable (private browsing etc.) -- just use the default
    }
  });
  // Aug 28 2026: table density preference, from the Settings module --
  // same read-with-fallback pattern as activeTab right above. Applied
  // as a class on the root div below (density-compact / density-
  // comfortable) so it cascades via CSS to every table in the app
  // without needing to touch each individual table component.
  const [density, setDensity] = useState(() => {
    try {
      const stored = localStorage.getItem('fo-radar-density');
      return ['comfortable', 'compact'].includes(stored) ? stored : 'comfortable';
    } catch {
      return 'comfortable';
    }
  });
  const [signalCount, setSignalCount] = useState(null);
  // Aug 28 2026: lifted verbatim from SignalList.jsx as part of the
  // top-nav redesign -- the underlying notification-firing logic
  // inside SignalList.jsx checks Notification.permission directly,
  // NOT this state variable, so it's untouched by this move. This
  // state is purely for the button's own display (on/off), which now
  // lives here instead.
  const [alertsEnabled, setAlertsEnabled] = useState(
    typeof Notification !== 'undefined' && Notification.permission === 'granted'
  );
  const enableAlerts = async () => {
    if (typeof Notification === 'undefined') {
      alert("Your browser doesn't support notifications.");
      return;
    }
    const perm = await Notification.requestPermission();
    setAlertsEnabled(perm === 'granted');
  };
  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen?.();
    } else {
      document.exitFullscreen?.();
    }
  };

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
    { id: 'dashboard', label: 'Dashboard', count: null },
    { id: 'signals', label: 'Live Signals', count: signalCount },
    { id: 'oi', label: 'OI Analytics', count: null },
    { id: 'index', label: 'Index Tracker', count: null },
    { id: 'market', label: 'Market View', count: null },
    { id: 'crude', label: 'Crude Oil', count: null },
    { id: 'bullion', label: 'Gold & Silver', count: null },
    { id: 'news', label: 'News', count: null },
    { id: 'value', label: 'Value Watchlist', count: null },
    { id: 'backtest', label: 'Daily Backtest', count: null },
    { id: 'settings', label: 'Settings', count: null },
    { id: 'strategy', label: 'Strategy Backtest', count: null },
  ];

  // Aug 28 2026: grouped nav layout, from the top-nav redesign
  // reference. Real tab names/ids throughout (not the mockup's own
  // labels like "Futures"/"Options"/"Analytics", which don't
  // correspond to anything that actually exists in this app) --
  // mapped honestly onto the 12 tabs that are real. Settings moved to
  // the gear icon in the top-right instead of living in this list
  // (see the icon row below) -- with every other tab accounted for
  // between the 3 standalone entries and the 2 groups, there was
  // nothing left over for a "More" dropdown, so it's omitted rather
  // than built empty just to visually match the reference.
  // Aug 28 2026: flat, single-row nav per direct feedback -- the
  // earlier grouped "Markets"/"Intelligence" structure is gone.
  // Aug 29 2026: Watchlist removed entirely (not just hidden) -- it
  // used the exact same useSignals() data as Live Signals, just fewer
  // columns; its one genuinely unique piece (52W High/Low + Technical)
  // folded into Live Signals' own detail drawer instead
  // (LiveSignalsTable.jsx). Order now: Dashboard, Live Signals, OI
  // Analytics, Index Tracker, Market View, Crude Oil, Gold & Silver,
  // News, Value Watchlist, Daily Backtest, Settings. 'strategy'
  // (Strategy Backtest) deliberately excluded from this visible list --
  // same feedback explicitly dropped it ("don't add more tabs just
  // because there's space"). Still reachable via direct navigation --
  // not deleted, just not competing for a slot in the primary nav.
  // Properly folding it into Daily Backtest as a sub-section (rather
  // than just hiding it) needs seeing that component first.
  const primaryNavOrder = ['dashboard', 'signals', 'oi', 'index', 'market', 'crude', 'bullion', 'news', 'value', 'backtest', 'settings'];
  const primaryTabs = primaryNavOrder.map(id => tabs.find(t => t.id === id)).filter(Boolean);

  const tabIcon = (id) => ({
    dashboard: '🏠', settings: '⚙️', signals: '⚡',
    oi: '📊', index: '📈', market: '📋', crude: '🛢️', bullion: '🥇',
    news: '📰', value: '💎', backtest: '🧮', strategy: '🧪',
  }[id] || '');

  const TabButton = ({ tab }) => (
    <button
      onClick={() => setActiveTab(tab.id)}
      className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap ${
        activeTab === tab.id
          ? 'bg-slate-700 text-white shadow-lg'
          : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
      }`}
    >
      {tabIcon(tab.id)} {tab.label}
      {tab.count !== null && (
        <span className={`text-xs px-1.5 py-0.5 rounded-full ${
          activeTab === tab.id ? 'bg-blue-500 text-white' : 'bg-slate-700 text-slate-300'
        }`}>
          {tab.count}
        </span>
      )}
    </button>
  );

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
    <div className={`min-h-screen bg-slate-950 text-white overflow-x-hidden ${theme === 'light' ? 'light' : ''} density-${density}`}>
      {/* Top nav row: logo and the icon cluster */}
      <div className="px-4 pt-4 pb-3 flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xl">🎯</span>
          <span className="font-bold text-white text-sm sm:text-base whitespace-nowrap">
            F&amp;O SNIPER <span className="text-slate-500 font-normal">SCANNER v3.0</span>
          </span>
        </div>
        <div className="flex items-center gap-1.5 ml-auto">
          <ThemeToggle />
          <button
            onClick={enableAlerts}
            disabled={alertsEnabled}
            title={alertsEnabled ? 'Alerts on' : 'Enable alerts'}
            aria-label={alertsEnabled ? 'Alerts on' : 'Enable alerts'}
            className={`w-9 h-9 flex items-center justify-center rounded-lg border transition-colors ${
              alertsEnabled
                ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/25 cursor-default'
                : 'text-amber-400 bg-amber-500/10 border-amber-500/25 hover:bg-amber-500/20'
            }`}
          >
            {alertsEnabled ? <IconBell size={16} /> : <IconBellOff size={16} />}
          </button>
          <button
            onClick={toggleFullscreen}
            title="Toggle fullscreen"
            aria-label="Toggle fullscreen"
            className="w-9 h-9 flex items-center justify-center rounded-lg border border-slate-700/50 bg-slate-900/50 text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          >
            <IconMaximize size={16} />
          </button>
        </div>
      </div>

      {/* Top Section */}
      <div className="px-4 pb-2">
        <MarketBanner />
        <MarketBreadth />
      </div>

      {/* Primary nav -- single flat row, exact order per direct
          feedback: don't add tabs just because there's space, and
          the earlier "Markets"/"Intelligence" grouping is gone. */}
      <div className="px-4 mb-4 flex gap-1 flex-wrap">
        {primaryTabs.map(tab => <TabButton key={tab.id} tab={tab} />)}
      </div>

      {/* Content Area — ONLY ONE TAB VISIBLE */}
      {/* Aug 22 2026: key={activeTab} forces React to remount this div
          on every tab switch (rather than just re-rendering the same
          node in place) -- that remount is what makes the CSS
          animation actually replay each time, instead of only firing
          once on the very first load. */}
      <div key={activeTab} className="px-4 pb-8 tab-fade-in">
        {activeTab === 'dashboard' && <Dashboard onNavigate={setActiveTab} />}
        {activeTab === 'settings' && <SettingsPanel onDensityChange={setDensity} />}
        {activeTab === 'signals' && <SignalList />}
        {activeTab === 'oi' && <Analytics />}
        {activeTab === 'index' && <IndexTracker />}
        {activeTab === 'market' && <MarketView />}
        {activeTab === 'crude' && <CrudeOilTracker />}
        {activeTab === 'bullion' && <BullionTracker />}
        {activeTab === 'news' && <NewsFeed />}
        {activeTab === 'value' && <FundamentalsWatchlist />}
        {activeTab === 'backtest' && <DailyBacktestTab />}
        {activeTab === 'strategy' && <StrategyBacktest />}
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AppShell />
    </ThemeProvider>
  );
}
