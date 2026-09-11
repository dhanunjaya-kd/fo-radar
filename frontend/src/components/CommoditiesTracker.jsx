import { useState } from 'react';
import CrudeOilTracker from './CrudeOilTracker';
import BullionTracker from './BullionTracker';

// Sep 11 2026: Crude Oil and Gold & Silver used to be two separate
// top-level nav tabs. Merged into one "Commodities" tab with these
// three sub-tabs so they live together. CrudeOilTracker is reused
// as-is (it already has its own Standard/Mini toggle internally);
// BullionTracker now takes an optional `metal` prop so it can show
// just Gold's or just Silver's Standard/Mini pair instead of all 4
// contracts at once -- see the comment above its export.
const SUB_TABS = [
  { id: 'crude', label: 'Crude', icon: '🛢️' },
  { id: 'gold', label: 'Gold', icon: '🥇' },
  { id: 'silver', label: 'Silver', icon: '🥈' },
];

export default function CommoditiesTracker() {
  const [subTab, setSubTab] = useState('crude');

  return (
    <div className="space-y-4">
      <div className="flex gap-1 bg-slate-900/50 p-1 rounded-xl w-fit">
        {SUB_TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setSubTab(t.id)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              subTab === t.id
                ? 'bg-slate-700 text-white shadow-lg'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {subTab === 'crude' && <CrudeOilTracker />}
      {subTab === 'gold' && <BullionTracker metal="GOLD" />}
      {subTab === 'silver' && <BullionTracker metal="SILVER" />}
    </div>
  );
}
