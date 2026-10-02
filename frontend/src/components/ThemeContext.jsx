import { createContext, useCallback, useContext, useEffect, useState } from 'react';

// Aug 21 2026: theme infrastructure. Deliberately does NOT rely on
// Tailwind's built-in dark: variant system (which needs darkMode:
// 'class' configured in tailwind.config.js -- a file this project
// hasn't had access to check) -- instead resolves to a plain 'light'
// or 'dark' string kept in React state/localStorage, applied as a
// className on the app root. A separate global stylesheet
// (theme-overrides.css) then overrides the specific Tailwind color
// classes already used throughout the app whenever that root class is
// 'light'. This means it works even for component files this session
// has never seen, without needing to touch them individually.

const ThemeContext = createContext(null);

const STORAGE_KEY = 'fo-radar-theme-mode'; // 'light' | 'dark' | 'system'

function getSystemPrefersDark() {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  } catch {
    return true; // matchMedia unavailable (very old browser) -- default to dark, matching this app's original design
  }
}

function resolveTheme(mode) {
  if (mode === 'system') return getSystemPrefersDark() ? 'dark' : 'light';
  return mode; // 'light' or 'dark' directly
}

export function ThemeProvider({ children }) {
  const [themeMode, setThemeModeState] = useState(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      // Sep 12 2026: default changed from 'system' to 'dark' -- a
      // first-time visitor on a light-mode OS was getting the light
      // theme by default (via resolveTheme('system') following their
      // OS), which is the reported "defaults to system instead of
      // dark" issue. Only the no-stored-value case changes here --
      // an explicit prior 'light' or 'system' selection is still
      // read back and honored exactly as before.
      return (stored === 'light' || stored === 'dark' || stored === 'system') ? stored : 'dark';
    } catch {
      return 'dark'; // localStorage unavailable (private browsing etc.) -- default to dark
    }
  });

  const [theme, setTheme] = useState(() => resolveTheme(themeMode));

  // Persist the MODE (light/dark/system), not the resolved theme --
  // if someone picked "system", switching OS theme later should keep
  // following it, not get stuck on whatever it resolved to at save time.
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, themeMode);
    } catch {
      // private browsing or similar -- not worth failing over, just skip persisting
    }
    setTheme(resolveTheme(themeMode));
  }, [themeMode]);

  // Live-follow OS theme changes while in "system" mode -- someone
  // toggling their OS from light to dark at 6pm shouldn't need to
  // reopen the app for this to catch up.
  useEffect(() => {
    if (themeMode !== 'system') return;
    let mql;
    try {
      mql = window.matchMedia('(prefers-color-scheme: dark)');
    } catch {
      return;
    }
    const handler = () => setTheme(resolveTheme('system'));
    mql.addEventListener?.('change', handler);
    return () => mql.removeEventListener?.('change', handler);
  }, [themeMode]);

  // `light` goes on <html> as well as on the app root: the page background (body) sits outside the
  // React root, and the Tailwind palette variables are defined on :root.light.
  useEffect(() => {
    document.documentElement.classList.toggle('light', theme === 'light');
  }, [theme]);

  const setThemeMode = (mode) => setThemeModeState(mode);

  return (
    <ThemeContext.Provider value={{ theme, themeMode, setThemeMode }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme() must be called inside a <ThemeProvider>');
  return ctx;
}

// Oct 2 2026: colours that have to be hex strings -- SVG/canvas drawing code, recharts props, chart
// libraries -- can't read the CSS palette, so they map through here. DARK returns the colour
// unchanged (dark rendering is exactly what it always was); LIGHT swaps the bright-on-dark hues for
// deeper ones that hold up on white, and the dark "chrome" greys for light ones. Anything not in the
// table passes through untouched.
const LIGHT_TONES = {
  // accents
  '#34d399': '#059669', '#10b981': '#059669', '#4ade80': '#16a34a', '#a3e635': '#65a30d',
  '#fb7185': '#e11d48', '#f87171': '#dc2626', '#ef4444': '#dc2626',
  '#fbbf24': '#d97706', '#facc15': '#ca8a04', '#fb923c': '#ea580c',
  '#60a5fa': '#2563eb', '#3b82f6': '#2563eb', '#38bdf8': '#0284c7', '#22d3ee': '#0891b2',
  '#818cf8': '#4f46e5', '#a78bfa': '#7c3aed', '#c084fc': '#9333ea', '#f472b6': '#db2777', '#2dd4bf': '#0d9488',
  // neutrals (text / lines / surfaces)
  '#f1f5f9': '#0f1f3d', '#e2e8f0': '#16294a', '#cbd5e1': '#2a3b5c', '#94a3b8': '#64748f',
  '#64748b': '#64748f', '#475569': '#97a3b8', '#334155': '#dfe5ee', '#1e293b': '#e8edf4',
  '#0f172a': '#ffffff', '#0b1220': '#ffffff', '#020617': '#eef1f6',
};
export const toneFor = (theme, hex) => (theme === 'light' && hex ? (LIGHT_TONES[String(hex).toLowerCase()] ?? hex) : hex);
export function useTone() {
  const { theme } = useTheme();
  return useCallback((hex) => toneFor(theme, hex), [theme]);
}

// Shared look for recharts / SVG chart chrome (grid, axis text, tooltip) in both themes.
export function useChartChrome() {
  const { theme } = useTheme();
  const L = theme === 'light';
  return {
    t: (hex) => toneFor(theme, hex),
    gridStroke: L ? '#dfe5ee' : '#334155',
    gridOpacity: L ? 1 : 0.3,
    tick: L ? '#64748f' : '#94a3b8',
    tooltip: { background: L ? '#ffffff' : '#0f172a', border: `1px solid ${L ? '#dfe5ee' : '#334155'}`, borderRadius: 6, fontSize: 11, boxShadow: L ? '0 8px 24px rgba(15,31,61,0.14)' : undefined },
    tooltipLabel: L ? '#0f1f3d' : '#e2e8f0',
  };
}
