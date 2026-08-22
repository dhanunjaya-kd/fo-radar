import { useTheme } from './ThemeContext';

const OPTIONS = [
  { mode: 'light', icon: '☀️', label: 'Light' },
  { mode: 'dark', icon: '🌙', label: 'Dark' },
  { mode: 'system', icon: '🖥️', label: 'System' },
];

export default function ThemeToggle() {
  const { themeMode, setThemeMode } = useTheme();

  return (
    <div className="flex items-center gap-0.5 bg-slate-900/50 p-0.5 rounded-lg" title="Theme">
      {OPTIONS.map(opt => (
        <button
          key={opt.mode}
          onClick={() => setThemeMode(opt.mode)}
          title={opt.label}
          aria-label={opt.label}
          className={`px-2 py-1.5 rounded-md text-xs transition-colors ${
            themeMode === opt.mode
              ? 'bg-slate-700 text-white'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
          }`}
        >
          {opt.icon}
        </button>
      ))}
    </div>
  );
}
