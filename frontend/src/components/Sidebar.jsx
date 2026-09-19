import { useState, useEffect } from 'react';

// Simple, consistent line icons -- same style as the existing IconBell/
// IconMaximize/IconLogOut already in App.jsx, one per nav item so the
// collapsed (icon-only) state is still recognizable, matching the
// reference sidebar's collapsed behavior.
const IconGrid = ({ size = 18 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>);
const IconTarget = ({ size = 18 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none"/></svg>);
const IconBarChart = ({ size = 18 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/></svg>);
const IconActivity = ({ size = 18 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>);
const IconRadar = ({ size = 18 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 12 L18 7"/><circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none"/></svg>);
const IconTrendingUp = ({ size = 18 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>);
const IconCalendar = ({ size = 18 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>);
const IconHistory = ({ size = 18 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v5h5"/><path d="M3.05 13a9 9 0 1 0 2.13-7.36L3 8"/><polyline points="12 7 12 12 16 14"/></svg>);
const IconLayers = ({ size = 18 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>);
const IconSettings = ({ size = 18 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>);
const IconBeaker = ({ size = 18 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 3h6"/><path d="M10 3v6l-6 10a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2l-6-10V3"/></svg>);
const IconChevronLeft = ({ size = 15 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6"/></svg>);
const IconChevronRight = ({ size = 15 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"/></svg>);
const IconFlame = ({ size = 18 }) => (<svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 17a2.5 2.5 0 0 0 2.5-2.5c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7.5 7.5 0 1 1-15 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg>);

const TAB_ICONS = {
  dashboard: IconGrid,
  signals: IconTarget,
  oi: IconBarChart,
  index: IconActivity,
  cas: IconRadar,
  market: IconTrendingUp,
  heatmap: IconFlame,
  nextday: IconCalendar,
  backtest: IconHistory,
  shadow: IconLayers,
  settings: IconSettings,
  strategy: IconBeaker,
};

/**
 * Sep 18 2026: collapsible left sidebar, replacing the horizontal tab
 * bar -- same tabs array/onSelect contract App.jsx already had for
 * TabButton, so App.jsx's own tab-switching logic (activeTab state,
 * localStorage persistence) didn't need to change, only how the list
 * of tabs gets rendered. Collapsed state (icon-only, matching the
 * reference's collapse behavior) is itself persisted so it survives a
 * reload, same pattern already used for activeTab/density elsewhere
 * in this app.
 */
export default function Sidebar({ tabs, activeTab, onSelect, brand }) {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('fo-radar-sidebar-collapsed') === 'true'; } catch { return false; }
  });

  useEffect(() => {
    try { localStorage.setItem('fo-radar-sidebar-collapsed', String(collapsed)); } catch {}
  }, [collapsed]);

  return (
    <div className={`sidebar-nav flex flex-col shrink-0 h-screen sticky top-0 border-r border-slate-800/60 bg-slate-950/60 transition-all duration-200 ${collapsed ? 'w-[64px]' : 'w-[220px]'}`}>
      <div className={`flex items-center gap-2.5 px-3 py-4 ${collapsed ? 'justify-center' : ''}`}>
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center shadow-lg shrink-0">
          <span className="text-white font-bold text-base leading-none">M</span>
        </div>
        {!collapsed && brand}
      </div>

      <button
        onClick={() => setCollapsed(c => !c)}
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        className={`mx-3 mb-3 flex items-center justify-center w-7 h-7 rounded-md border border-slate-700/60 text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 transition-colors ${collapsed ? '' : 'self-end mr-3'}`}
      >
        {collapsed ? <IconChevronRight /> : <IconChevronLeft />}
      </button>

      <nav className="flex-1 overflow-y-auto px-2 space-y-1">
        {tabs.map(tab => {
          const Icon = TAB_ICONS[tab.id] || IconGrid;
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => onSelect(tab.id)}
              title={collapsed ? tab.label : undefined}
              className={`w-full flex items-center gap-2.5 rounded-lg text-sm font-medium transition-all whitespace-nowrap ${collapsed ? 'justify-center px-0 py-2.5' : 'px-3 py-2.5'} ${active ? 'bg-slate-700 text-white shadow-lg' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'}`}
            >
              <Icon size={18} />
              {!collapsed && <span className="flex-1 text-left truncate">{tab.label}</span>}
              {!collapsed && tab.count !== null && (
                <span className={`text-xs px-1.5 py-0.5 rounded-full ${active ? 'bg-blue-500 text-white' : 'bg-slate-700 text-slate-300'}`}>{tab.count}</span>
              )}
              {collapsed && tab.count !== null && tab.count > 0 && (
                <span className="absolute translate-x-2.5 -translate-y-2.5 w-2 h-2 rounded-full bg-blue-500" />
              )}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
