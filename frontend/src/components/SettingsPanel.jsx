import { useState } from 'react';

// Aug 28 2026: tested in isolation (test_density_preference.js) before
// this component was written. Same fallback pattern App.jsx already
// uses for activeTab -- invalid/missing/inaccessible storage all
// degrade safely to 'comfortable', never a crash.
const DENSITY_KEY = 'fo-radar-density';
const VALID_DENSITIES = ['comfortable', 'compact'];

function readDensityPreference() {
  try {
    const stored = localStorage.getItem(DENSITY_KEY);
    return VALID_DENSITIES.includes(stored) ? stored : 'comfortable';
  } catch (e) {
    return 'comfortable';
  }
}

function writeDensityPreference(value) {
  if (!VALID_DENSITIES.includes(value)) return false;
  try {
    localStorage.setItem(DENSITY_KEY, value);
    return true;
  } catch (e) {
    return false;
  }
}

// Aug 28 2026: this project's actual Settings scope, confirmed before
// building anything -- Theme is already handled by an existing
// useTheme() hook (the sun/moon icon already in the top nav), and
// which tab you land on already persists automatically via
// localStorage('fo-radar-active-tab') -- REMEMBERING your last tab,
// not a separately user-chosen "default page." Building competing
// controls for either here would conflict with what already works,
// not add anything. Notifications (browser/sound alerts) already have
// their own toggle in the Live Signals tab. Density is the one
// genuinely new, uncovered preference -- applied globally via a CSS
// class on the app root (see App.jsx), not by touching every
// individual table component.
export default function SettingsPanel({ onDensityChange }) {
  const [density, setDensity] = useState(readDensityPreference);
  const [saved, setSaved] = useState(false);

  const handleDensityChange = (value) => {
    setDensity(value);
    const ok = writeDensityPreference(value);
    if (ok && onDensityChange) onDensityChange(value);
    setSaved(ok);
    setTimeout(() => setSaved(false), 1500);
  };

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4 max-w-lg">
      <h3 className="text-sm font-bold text-white mb-3">Settings</h3>

      <div className="mb-4">
        <p className="text-xs font-medium text-slate-300 mb-1.5">Table Density</p>
        <div className="flex gap-1 bg-slate-900/50 p-0.5 rounded-lg w-fit">
          {VALID_DENSITIES.map(d => (
            <button
              key={d}
              onClick={() => handleDensityChange(d)}
              className={`text-xs font-medium px-3 py-1.5 rounded-md transition-colors capitalize ${
                density === d ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {d}
            </button>
          ))}
        </div>
        {saved && <p className="text-[10px] text-emerald-400 mt-1.5">Saved</p>}
      </div>

      <div className="border-t border-slate-700/40 pt-3 space-y-1.5">
        <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Already available elsewhere</p>
        <p className="text-xs text-slate-400">🎨 Theme — sun/moon icon, top navigation bar</p>
        <p className="text-xs text-slate-400">🔔 Notification alerts — toggle in the Live Signals tab</p>
        <p className="text-xs text-slate-400">📍 Default tab — remembers whichever tab you last had open</p>
      </div>
    </div>
  );
}
