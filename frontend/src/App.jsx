import { useState, useEffect } from 'react';
import { fyersSocket } from './services/fyersSocket';
import api from './services/api';
import { ThemeProvider, useTheme } from './components/ThemeContext';
import ThemeToggle from './components/ThemeToggle';
import './components/theme-overrides.css';
import './components/density-overrides.css';
import MarketBanner from './components/MarketBanner';
import MarketStatusHeader from './components/MarketStatusHeader';
import SignalList from './components/SignalList';
import Analytics from './components/Analytics';
import IndexTracker from './components/IndexTracker';
import MarketView from './components/MarketView';
import CommoditiesTracker from './components/CommoditiesTracker';
import NextDayWatchlist from './components/NextDayWatchlist';
import DailyBacktestTab from './components/DailyBacktestTab';
import ShadowSignals from './components/ShadowSignals';
import Dashboard from './components/Dashboard';
import SettingsPanel from './components/SettingsPanel';
import StrategyBacktest from './components/StrategyBacktest';
import CASRadar from './components/CASRadar';

const API_BASE = import.meta.env.VITE_API_URL || '';

const IconBell = ({ size = 16 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-9-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>);
const IconBellOff = ({ size = 16 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M13.73 21a2 2 0 0 1-3.46 0"/><path d="M18.63 13A17.89 17.89 0 0 1 18 8"/><path d="M6.26 6.26A5.86 5.86 0 0 0 6 8c0 7-3 9-3 9h14"/><path d="M18 8a6 6 0 0 0-9.33-5"/><line x1="1" y1="1" x2="23" y2="23"/></svg>);
const IconMaximize = ({ size = 17 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>);
const IconLogOut = ({ size = 16 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>);

const VALID_TABS = ['dashboard', 'signals', 'oi', 'index', 'cas', 'market', 'commodities', 'nextday', 'backtest', 'shadow', 'settings', 'strategy'];

function AppShell() {
  const { theme } = useTheme();
  const [activeTab, setActiveTab] = useState(() => {
    try { const stored = localStorage.getItem('fo-radar-active-tab'); return VALID_TABS.includes(stored) ? stored : 'signals'; } catch { return 'signals'; }
  });
  const [density, setDensity] = useState(() => {
    try { const stored = localStorage.getItem('fo-radar-density'); return ['comfortable', 'compact'].includes(stored) ? stored : 'comfortable'; } catch { return 'comfortable'; }
  });
  const [signalCount, setSignalCount] = useState(null);
  const [alertsEnabled, setAlertsEnabled] = useState(typeof Notification !== 'undefined' && Notification.permission === 'granted');

  const enableAlerts = async () => {
    if (typeof Notification === 'undefined') { alert("Your browser doesn't support notifications."); return; }
    const perm = await Notification.requestPermission();
    setAlertsEnabled(perm === 'granted');
  };
  const toggleFullscreen = () => { if (!document.fullscreenElement) document.documentElement.requestFullscreen?.(); else document.exitFullscreen?.(); };

  const [disconnecting, setDisconnecting] = useState(false);
  const disconnectFyers = async () => {
    if (!window.confirm('This disconnects Fyers and stops all live data across the app until you re-run get_fyers_token.py. Continue?')) return;
    setDisconnecting(true);
    try {
      const res = await fetch(`${API_BASE}/api/fyers-disconnect/`, { method: 'POST' });
      const json = await res.json();
      if (!res.ok || json.error) throw new Error(json.error || `HTTP ${res.status}`);
      alert('Disconnected. Run get_fyers_token.py to reconnect.');
    } catch (err) { alert(`Disconnect failed: ${err.message}`); } finally { setDisconnecting(false); }
  };

  useEffect(() => { try { localStorage.setItem('fo-radar-active-tab', activeTab); } catch {} }, [activeTab]);

  const tabs = [
    { id: 'dashboard', label: 'Dashboard', count: null },
    { id: 'signals', label: 'Sniper Signals', count: signalCount },
    { id: 'oi', label: 'Open Interest Analytics', count: null },
    { id: 'index', label: 'Index Monitor', count: null },
    { id: 'cas', label: 'CAS Radar', count: null },
    { id: 'market', label: 'Market Overview', count: null },
    { id: 'commodities', label: 'Commodities', count: null },
    { id: 'nextday', label: "Next-Day Watchlist", count: null },
    { id: 'backtest', label: 'Daily Backtest', count: null },
    { id: 'shadow', label: 'Simulation', count: null },
    { id: 'settings', label: 'Settings', count: null },
    { id: 'strategy', label: 'Strategy Backtest', count: null },
  ];

  const primaryNavOrder = ['dashboard', 'signals', 'oi', 'index', 'cas', 'market', 'commodities', 'nextday', 'backtest', 'shadow', 'settings'];
  const primaryTabs = primaryNavOrder.map(id => tabs.find(t => t.id === id)).filter(Boolean);

  const TabButton = ({ tab }) => (
    <button onClick={() => setActiveTab(tab.id)} className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap ${activeTab === tab.id ? 'bg-slate-700 text-white shadow-lg' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'}`}>
      {tab.label}
      {tab.count !== null && <span className={`text-xs px-1.5 py-0.5 rounded-full ${activeTab === tab.id ? 'bg-blue-500 text-white' : 'bg-slate-700 text-slate-300'}`}>{tab.count}</span>}
    </button>
  );

  useEffect(() => {
    let cancelled = false;
    const loadCounts = () => {
      api.getSignals?.().then((res) => { if (cancelled || !res) return; const list = Array.isArray(res) ? res : (res.signals || []); setSignalCount(list.length); }).catch(() => {});
    };
    loadCounts();
    const interval = setInterval(loadCounts, 15000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const primeTokenAndConnect = async () => {
      try {
        const res = await api.getFyersBrowserToken();
        if (!cancelled && res?.authenticated && res.access_token) {
          localStorage.setItem('fyers_access_token', res.access_token);
          localStorage.setItem('fyers_app_id', res.app_id);
        }
      } catch (e) { console.warn('Could not fetch Fyers token for live ticks:', e.message); }
      if (!cancelled) fyersSocket.connect();
    };
    primeTokenAndConnect();
    return () => fyersSocket.disconnect();
  }, []);

  return (
    <div className={`min-h-screen bg-slate-950 text-white overflow-x-hidden ${theme === 'light' ? 'light' : ''} density-${density}`}>
      <div className="px-4 pt-4 pb-3 flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2.5 shrink-0">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center shadow-lg shrink-0">
            <span className="text-white font-bold text-base leading-none">M</span>
          </div>
          <div className="leading-tight">
            <div className="font-bold text-white text-sm sm:text-base tracking-wide whitespace-nowrap">MARKETEDGE</div>
            <div className="text-[10px] text-slate-500 font-medium tracking-wide whitespace-nowrap">Market Intelligence Terminal</div>
          </div>
        </div>
        <MarketStatusHeader />
        <div className="flex items-center gap-1.5 ml-auto"><ThemeToggle /><button onClick={enableAlerts} disabled={alertsEnabled} title={alertsEnabled ? 'Alerts on' : 'Enable alerts'} aria-label={alertsEnabled ? 'Alerts on' : 'Enable alerts'} className={`w-9 h-9 flex items-center justify-center rounded-lg border transition-colors ${alertsEnabled ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/25 cursor-default' : 'text-amber-400 bg-amber-500/10 border-amber-500/25 hover:bg-amber-500/20'}`}>{alertsEnabled ? <IconBell size={16} /> : <IconBellOff size={16} />}</button><button onClick={toggleFullscreen} title="Toggle fullscreen" aria-label="Toggle fullscreen" className="w-9 h-9 flex items-center justify-center rounded-lg border border-slate-700/50 bg-slate-900/50 text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"><IconMaximize size={16} /></button><button onClick={disconnectFyers} disabled={disconnecting} title="Disconnect Fyers" aria-label="Disconnect Fyers" className={`w-9 h-9 flex items-center justify-center rounded-lg border transition-colors ${disconnecting ? 'text-slate-500 bg-slate-800 border-slate-700 cursor-wait' : 'text-rose-400 bg-rose-500/10 border-rose-500/25 hover:bg-rose-500/20'}`}><IconLogOut size={16} /></button></div>
      </div>
      <div className="px-4 pb-2"><MarketBanner /></div>
      <div className="px-4 mb-4 flex gap-1 flex-wrap">{primaryTabs.map(tab => <TabButton key={tab.id} tab={tab} />)}</div>
      <div key={activeTab} className="px-4 pb-8 tab-fade-in">
        {activeTab === 'dashboard' && <Dashboard onNavigate={setActiveTab} />}
        {activeTab === 'settings' && <SettingsPanel onDensityChange={setDensity} />}
        {activeTab === 'signals' && <SignalList />}
        {activeTab === 'oi' && <Analytics />}
        {activeTab === 'index' && <IndexTracker />}
        {activeTab === 'cas' && <CASRadar />}
        {activeTab === 'market' && <MarketView />}
        {activeTab === 'commodities' && <CommoditiesTracker />}
        {activeTab === 'nextday' && <NextDayWatchlist />}
        {activeTab === 'backtest' && <DailyBacktestTab />}
        {activeTab === 'shadow' && <ShadowSignals />}
        {activeTab === 'strategy' && <StrategyBacktest />}
      </div>
    </div>
  );
}

export default function App() { return <ThemeProvider><AppShell /></ThemeProvider>; }
