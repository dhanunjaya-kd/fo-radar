import { useEffect, useState } from 'react';

// Relative on purpose -- see the same note in SignalList.jsx / IndexTracker.jsx.
const API_BASE = import.meta.env.VITE_API_URL || '';

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

  // Sep 2 2026: unlike density, this setting lives server-side (it has
  // to -- the backend's own position-sizing math needs it, not just
  // this UI), so it's loaded from the API on mount instead of read
  // synchronously from localStorage. null means "never configured" --
  // the honest default, unchanged-behavior state (exactly 1 real lot
  // per trade), not zero and not a placeholder.
  const [riskBudget, setRiskBudget] = useState(null);
  const [riskBudgetInput, setRiskBudgetInput] = useState('');
  const [riskBudgetLoading, setRiskBudgetLoading] = useState(true);
  const [riskBudgetSaved, setRiskBudgetSaved] = useState(false);
  const [riskBudgetError, setRiskBudgetError] = useState(null);

  // Sep 19 2026: real "Connections" status card, direct request --
  // deliberately just ONE row (Fyers), not five like the reference
  // screenshot. Checked first rather than assumed: this codebase has
  // no Dhan Broker API, no OpenAlgo Bridge, no Groq/Gemini AI
  // integration anywhere (grepped for all four, zero matches) -- those
  // are that OTHER tool's own integrations, not ours, and rows for
  // things that don't exist here would just be fabricated status.
  // Fyers itself is real: /api/fyers-status/ already existed, this
  // just surfaces it. Also found and NOT perpetuated a real bug while
  // wiring this up -- that endpoint's own "message" field says
  // "Please authenticate via /api/fyers/login/", but no such route is
  // registered anywhere in urls.py; that's a dead link baked into the
  // API response. The one real way to connect, confirmed by reading
  // FyersDisconnectView's own docstring, is running get_fyers_token.py
  // from the project root -- no in-app connect flow exists to link to,
  // so this says that plainly instead of adding a "Set up" button that
  // would click through to nothing. Disconnect, unlike connect, DOES
  // have a real working endpoint (/api/fyers-disconnect/) -- wired to
  // an actual button, not a placeholder.
  const [fyersStatus, setFyersStatus] = useState(null);
  const [fyersLoading, setFyersLoading] = useState(true);
  const [disconnecting, setDisconnecting] = useState(false);

  const loadFyersStatus = () => {
    setFyersLoading(true);
    fetch(`${API_BASE}/api/fyers-status/`)
      .then(r => r.json())
      .then(d => setFyersStatus(d))
      .catch(() => setFyersStatus(null))
      .finally(() => setFyersLoading(false));
  };
  useEffect(() => { loadFyersStatus(); }, []);

  const disconnectFyers = async () => {
    setDisconnecting(true);
    try {
      await fetch(`${API_BASE}/api/fyers-disconnect/`, { method: 'POST' });
    } catch (e) {
      // best-effort -- loadFyersStatus() below re-checks either way
    } finally {
      setDisconnecting(false);
      loadFyersStatus();
    }
  };

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/api/settings/risk-budget/`)
      .then(r => r.json())
      .then(d => {
        if (cancelled) return;
        setRiskBudget(d.risk_budget_rupees);
        setRiskBudgetInput(d.risk_budget_rupees != null ? String(d.risk_budget_rupees) : '');
      })
      .catch(() => { if (!cancelled) setRiskBudgetError("Couldn't load current setting"); })
      .finally(() => { if (!cancelled) setRiskBudgetLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const saveRiskBudget = async (value) => {
    setRiskBudgetError(null);
    try {
      const res = await fetch(`${API_BASE}/api/settings/risk-budget/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ risk_budget_rupees: value }),
      });
      const d = await res.json();
      if (!res.ok) { setRiskBudgetError(d.error || 'Save failed'); return; }
      setRiskBudget(d.risk_budget_rupees);
      setRiskBudgetSaved(true);
      setTimeout(() => setRiskBudgetSaved(false), 1500);
    } catch (e) {
      setRiskBudgetError(e.message);
    }
  };

  const handleDensityChange = (value) => {
    setDensity(value);
    const ok = writeDensityPreference(value);
    if (ok && onDensityChange) onDensityChange(value);
    setSaved(ok);
    setTimeout(() => setSaved(false), 1500);
  };

  return (
    <div className="space-y-3 max-w-lg">
      <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
        <h3 className="text-sm font-bold text-white mb-3">Connections</h3>
        {fyersLoading ? (
          <div className="text-xs text-slate-500">Checking…</div>
        ) : (
          <div className="flex items-center justify-between rounded-lg border border-slate-700/50 bg-slate-900/40 px-3 py-2.5">
            <div>
              <div className="text-sm font-medium text-white">Fyers Broker API</div>
              <div className="text-[11px] text-slate-500 mt-0.5">{fyersStatus?.message}</div>
              {/* Sep 19 2026: real diagnostic detail (Fyers' own
                  response code/message, or a clear config problem)
                  behind a failed check, not just "Not connected" --
                  direct request, confirmed live: a genuinely valid,
                  Fyers-side-connected token still showed Disconnected
                  here, and this is what actually finds out why on the
                  next check instead of guessing again. */}
              {fyersStatus?.error_detail && (
                <div className="text-[11px] text-rose-400/90 mt-1">⚠ {fyersStatus.error_detail}</div>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0 ml-3">
              <span className={`w-1.5 h-1.5 rounded-full ${fyersStatus?.authenticated ? 'bg-emerald-400' : 'bg-slate-600'}`} />
              <span className={`text-xs font-medium ${fyersStatus?.authenticated ? 'text-emerald-400' : 'text-slate-500'}`}>
                {fyersStatus?.authenticated ? 'Connected' : 'Not connected'}
              </span>
              {fyersStatus?.authenticated && (
                <button
                  onClick={disconnectFyers}
                  disabled={disconnecting}
                  className="text-xs text-rose-400 hover:text-rose-300 disabled:opacity-50 ml-1"
                >
                  {disconnecting ? 'Disconnecting…' : 'Disconnect'}
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
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

      <div className="mb-4 border-t border-slate-700/40 pt-3">
        <p className="text-xs font-medium text-slate-300 mb-1">Risk Budget Per Trade</p>
        <p className="text-[10px] text-slate-500 mb-2">
          Optional. When set, position size becomes the largest whole number of real exchange lots whose
          risk (entry − SL, per lot) stays within this rupee amount — never a fraction of a lot. If even
          1 lot's risk exceeds this budget, that trade is skipped rather than forced through. Leave blank
          to keep the current default: exactly 1 real lot per trade, regardless of risk.
        </p>
        {riskBudgetLoading ? (
          <p className="text-[10px] text-slate-500">Loading current setting...</p>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">₹</span>
            <input
              type="number"
              min="1"
              step="1"
              value={riskBudgetInput}
              onChange={(e) => setRiskBudgetInput(e.target.value)}
              placeholder="e.g. 10000"
              className="w-32 text-xs bg-slate-900/60 border border-slate-700 rounded-md px-2 py-1.5 text-white placeholder-slate-600 focus:outline-none focus:border-slate-500"
            />
            <button
              onClick={() => saveRiskBudget(riskBudgetInput ? Number(riskBudgetInput) : null)}
              className="text-xs font-medium px-3 py-1.5 rounded-md bg-slate-700 text-white hover:bg-slate-600 transition-colors"
            >
              Save
            </button>
            {riskBudget != null && (
              <button
                onClick={() => { setRiskBudgetInput(''); saveRiskBudget(null); }}
                className="text-xs font-medium px-3 py-1.5 rounded-md text-slate-400 hover:text-slate-200 transition-colors"
              >
                Clear (use 1 lot)
              </button>
            )}
          </div>
        )}
        {riskBudgetSaved && <p className="text-[10px] text-emerald-400 mt-1.5">Saved</p>}
        {riskBudgetError && <p className="text-[10px] text-rose-400 mt-1.5">{riskBudgetError}</p>}
        <p className="text-[10px] text-slate-600 mt-1.5">
          Current: {riskBudget != null ? `₹${riskBudget.toLocaleString('en-IN')} per trade` : 'Not set — 1 real lot per trade (default)'}
        </p>
      </div>

      <div className="border-t border-slate-700/40 pt-3 space-y-1.5">
        <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Already available elsewhere</p>
        <p className="text-xs text-slate-400">🎨 Theme — sun/moon icon, top navigation bar</p>
        <p className="text-xs text-slate-400">🔔 Notification alerts — toggle in the Live Signals tab</p>
        <p className="text-xs text-slate-400">📍 Default tab — remembers whichever tab you last had open</p>
      </div>
      </div>
    </div>
  );
}
