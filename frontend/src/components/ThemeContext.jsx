import { createContext, useContext, useEffect, useState } from 'react';

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
