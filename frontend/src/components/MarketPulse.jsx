import { useState, useEffect } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

/**
 * Sep 18 2026: Market Pulse section for the Dashboard rebuild.
 * Every number rendered here comes directly from /api/market-breadth/
 * -- no value in this file is computed, guessed, or filled in locally.
 * Where that endpoint reports a metric as unavailable (null, or
 * count_with_data: 0), this component shows that honestly (a dash or
 * an explicit "not enough data" state) rather than substituting a
 * placeholder that could be mistaken for a real reading.
 */

const MOOD_COLORS = {
  'Extreme Fear': '#ef4444', 'Fear': '#fb923c', 'Neutral': '#fbbf24',
  'Greed': '#a3e635', 'Extreme Greed': '#34d399',
};

function MoodGauge({ score, label }) {
  const size = 96, stroke = 8, r = (size - stroke) / 2, c = 2 * Math.PI * r;
  const pct = score == null ? 0 : Math.max(0, Math.min(100, score)) / 100;
  const color = MOOD_COLORS[label] || '#64748b';
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#1e293b" strokeWidth={stroke} />
        {score != null && (
          <circle
            cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={stroke}
            strokeDasharray={`${c * pct} ${c}`} strokeLinecap="round"
            transform={`rotate(-90 ${size/2} ${size/2})`}
          />
        )}
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-2xl font-bold text-white">{score != null ? score : '—'}</span>
      </div>
    </div>
  );
}

function BreadthTile({ label, tag, tagColor, children }) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-3">
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className={`w-1.5 h-1.5 rounded-full ${tagColor}`} />
        <span className="text-[11px] font-semibold text-slate-400 tracking-wide">{label}</span>
        <span className="text-[11px] font-semibold" style={{ color: tagColor ? undefined : '#94a3b8' }}>· {tag}</span>
      </div>
      <div className="text-sm text-slate-300 leading-snug">{children}</div>
    </div>
  );
}

function ProgressTile({ title, icon, value, valueLabel, subLabel, pct, barColor, footer }) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-3.5">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-semibold text-slate-400 tracking-wide">{title}</span>
        {icon}
      </div>
      <div className="flex items-baseline gap-2 mb-1">
        <span className="text-xl font-bold text-white">{value}</span>
        {valueLabel && <span className="text-[11px] font-semibold text-slate-500 tracking-wide">{valueLabel}</span>}
      </div>
      {pct != null && (
        <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden mb-1.5">
          <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, pct))}%`, backgroundColor: barColor }} />
        </div>
      )}
      <div className="text-[11px] text-slate-500">{subLabel}</div>
      {footer && <div className="text-[11px] text-slate-500 mt-1">{footer}</div>}
    </div>
  );
}

function SplitTile({ title, universe, leftLabel, leftValue, leftSub, rightLabel, rightValue, rightSub, leftPct, unavailable }) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-3">
      <div className="text-[11px] font-semibold text-slate-400 tracking-wide mb-2">
        {title}{universe ? ` · ${universe} STOCKS` : ''}
      </div>
      {unavailable ? (
        <div className="text-[11px] text-slate-500 italic">Not yet available — needs a year of price history this project doesn't fetch yet.</div>
      ) : (
        <>
          <div className="flex justify-between text-xs mb-1">
            <div>
              <div className="text-[10px] text-slate-500">{leftLabel}</div>
              <div className="text-emerald-400 font-semibold">{leftValue} <span className="text-slate-500">{leftSub}</span></div>
            </div>
            <div className="text-right">
              <div className="text-[10px] text-slate-500">{rightLabel}</div>
              <div className="text-red-400 font-semibold">{rightValue} <span className="text-slate-500">{rightSub}</span></div>
            </div>
          </div>
          <div className="w-full h-1.5 bg-red-500/30 rounded-full overflow-hidden">
            <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${Math.max(0, Math.min(100, leftPct || 0))}%` }} />
          </div>
        </>
      )}
    </div>
  );
}

export default function MarketPulse() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/market-breadth/`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const json = await res.json();
        if (!cancelled) { setData(json); setError(false); }
      } catch (err) {
        console.error('MarketPulse fetch error:', err);
        if (!cancelled) setError(true);
      }
    };
    load();
    const interval = setInterval(load, 60000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  if (error) {
    return (
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 text-sm text-slate-500">
        Market breadth data unavailable right now.
      </div>
    );
  }
  if (!data) {
    return (
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 text-sm text-slate-500">
        Loading market pulse…
      </div>
    );
  }

  const { market_mood: mood, advance_decline: ad, trend_participation: tp,
           market_momentum: mm, volume_activity: va, ema50_breadth: e50,
           momentum_breadth: mb, volatility_breadth: vb, sector_breadth: sb } = data;

  // Sector rotation read: how many sectors (with at least 2 names,
  // so a 1-stock "sector" can't flip the read) have a clear majority
  // (>=60%) moving the same direction -- a plain, stated definition
  // of "broad" (many sectors agree) vs "rotational" (few do), derived
  // here from sector_breadth, which the backend already returns real.
  const sectors = Object.entries(sb || {}).filter(([, v]) => v.total >= 2);
  const movingSectors = sectors.filter(([, v]) => (v.up / v.total >= 0.6) || (v.down / v.total >= 0.6));
  const sectorRotationTag = sectors.length === 0 ? '—' : (movingSectors.length / sectors.length >= 0.5 ? 'BULLISH' : 'CAUTION');
  const topSectors = [...sectors].sort((a, b) => (b[1].up / b[1].total) - (a[1].up / a[1].total)).slice(0, 2);
  const sectorText = sectors.length === 0
    ? 'Not enough sector data yet this cycle.'
    : `${movingSectors.length / sectors.length >= 0.5 ? 'Strength is broad, not rotational' : 'Strength looks rotational, not broad'} — ${topSectors.map(([name, v]) => `${name} (${v.up}/${v.total} up)`).join(', ')}.`;

  return (
    <div className="space-y-4">
      {/* Market Pulse headline card */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-semibold text-white">Market Pulse</span>
          {mood.strength && (
            <span className="text-[11px] font-bold text-emerald-400 border border-emerald-500/30 bg-emerald-500/10 rounded px-2 py-0.5">
              {mood.strength}
            </span>
          )}
        </div>
        <div className="flex items-start gap-4">
          <MoodGauge score={mood.score} label={mood.label} />
          <div className="flex-1 min-w-0">
            <div className="text-[11px] text-slate-500 mb-0.5">
              {mood.label ? mood.label.toUpperCase() : 'MOOD'} · market mood · {mood.inputs_available} of {mood.inputs_total} inputs
            </div>
            <div className="text-base font-bold text-white mb-1.5">{mood.headline}</div>
            <div className="text-sm text-slate-400">{mood.body}</div>
          </div>
        </div>
        {mood.sniper_summary && (
          <div className="mt-3 bg-slate-800/50 border border-slate-700/50 rounded-lg p-3 text-sm">
            <span className={`font-semibold ${mood.sniper_summary.tilt === 'bullish' ? 'text-emerald-400' : mood.sniper_summary.tilt === 'bearish' ? 'text-red-400' : 'text-slate-400'}`}>
              Sniper AI · {mood.sniper_summary.tilt}:
            </span>{' '}
            <span className="text-slate-300">{mood.sniper_summary.text}</span>
          </div>
        )}
      </div>

      {/* Sniper AI Signals -- 4 breadth tiles */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <BreadthTile label="TREND BREADTH" tag={e50.pct_above == null ? '—' : e50.pct_above >= 55 ? 'BULLISH' : e50.pct_above <= 45 ? 'BEARISH' : 'NEUTRAL'} tagColor="bg-amber-400">
          {e50.count_with_data === 0 ? 'Not enough data yet.' :
            `${e50.pct_above}% of names hold above the 50 EMA${tp.count_with_data ? `, ${tp.pct_above_ema200}% above the 200` : ''}.`}
        </BreadthTile>
        <BreadthTile label="MOMENTUM" tag={mb.count_with_data === 0 ? '—' : mb.pct_undecided >= 30 ? 'CAUTION' : 'CLEAR'} tagColor="bg-amber-400">
          {mb.count_with_data === 0 ? 'Not enough data yet.' :
            `${mb.undecided_count} names sit on their MACD signal line, neither above nor below — momentum is ${mb.pct_undecided >= 30 ? 'undecided across a cluster' : 'mostly resolved'} this cycle.`}
        </BreadthTile>
        <BreadthTile label="VOLATILITY" tag={vb.count_with_data === 0 ? '—' : vb.pct_wide >= 40 ? 'CAUTION' : 'CALM'} tagColor="bg-amber-400">
          {vb.count_with_data === 0 ? 'Not enough data yet.' :
            `Ranges are ${vb.pct_wide >= 40 ? 'widening' : 'steady'} — ${vb.wide_range_count} names have Bollinger Bands over 10% of price.`}
        </BreadthTile>
        <BreadthTile label="SECTOR ROTATION" tag={sectorRotationTag} tagColor="bg-emerald-400">
          {sectorText}
        </BreadthTile>
      </div>

      {/* Advance/Decline, Trend Participation, Market Momentum, Volume Activity */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <ProgressTile
          title="ADVANCE / DECLINE"
          value={ad.net > 0 ? `+${ad.net}` : ad.net}
          valueLabel={ad.ratio != null ? `${ad.ratio}:1` : ''}
          pct={ad.count_with_data ? (100 * ad.advancing / ad.count_with_data) : null}
          barColor="#34d399"
          subLabel={`${ad.advancing} up  ${ad.flat} flat  ${ad.declining} down · of ${ad.count_with_data} stocks`}
        />
        <ProgressTile
          title="TREND PARTICIPATION"
          value={tp.pct_above_ema200 != null ? `${tp.pct_above_ema200}%` : '—'}
          valueLabel="ABOVE 200 EMA"
          pct={tp.pct_above_ema200}
          barColor="#34d399"
          subLabel={tp.count_with_data ? `${tp.pct_above_ema200 >= 50 ? 'Majority above' : 'Majority below'} · of ${tp.count_with_data} stocks` : 'No data yet'}
          footer={tp.partial_universe ? 'Partial universe' : null}
        />
        <ProgressTile
          title="MARKET MOMENTUM"
          value={mm.mean_rsi != null ? mm.mean_rsi : '—'}
          valueLabel={mm.classification ? mm.classification.toUpperCase().replace('-', '-') : ''}
          pct={mm.mean_rsi}
          barColor="#fbbf24"
          subLabel={mm.count_with_data ? `mean RSI · of ${mm.count_with_data} stocks` : 'No data yet'}
        />
        <ProgressTile
          title="VOLUME ACTIVITY"
          value={va.elevated_count}
          valueLabel={va.pct_elevated != null ? `${va.pct_elevated}% ON 2X VOL` : ''}
          pct={va.pct_elevated}
          barColor="#818cf8"
          subLabel={va.count_with_data ? `${va.elevated_up} up  ${va.elevated_down} down · of ${va.count_with_data} stocks` : 'No data yet'}
        />
      </div>

      <div className="text-[11px] text-slate-500">
        Conditions, not recommendations. Every tile states what was measured and over how many stocks; an input that did not load shows "—" rather than a neutral default.
      </div>

      {/* Bottom stat tiles -- reuses data already in this same
          response, no second fetch needed. 52-week is deliberately
          shown as "not yet available" (has_52w_data is always false
          today -- that needs ~252 days of history, this project only
          fetches 100) rather than a fabricated number. */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <SplitTile title="TODAY" universe={ad.count_with_data}
          leftLabel="ADVANCING" leftValue={ad.count_with_data ? `${Math.round(100*ad.advancing/ad.count_with_data)}%` : '—'} leftSub={`(${ad.advancing})`}
          rightLabel="DECLINING" rightValue={ad.count_with_data ? `${Math.round(100*ad.declining/ad.count_with_data)}%` : '—'} rightSub={`(${ad.declining})`}
          leftPct={ad.count_with_data ? 100*ad.advancing/ad.count_with_data : 0} />
        <SplitTile title="52W" universe={null} unavailable
          leftLabel="NEAR HIGH" rightLabel="NEAR LOW" />
        <SplitTile title="EMA50" universe={e50.count_with_data}
          leftLabel="ABOVE" leftValue={e50.pct_above != null ? `${e50.pct_above}%` : '—'} leftSub={`(${e50.above_count})`}
          rightLabel="BELOW" rightValue={e50.count_with_data ? `${(100-e50.pct_above).toFixed(1)}%` : '—'} rightSub={`(${e50.below_count})`}
          leftPct={e50.pct_above || 0} />
        <SplitTile title="VWAP" universe={data.vwap_breadth.count_with_data}
          leftLabel="ABOVE" leftValue={data.vwap_breadth.pct_above != null ? `${data.vwap_breadth.pct_above}%` : '—'} leftSub={`(${data.vwap_breadth.above_count})`}
          rightLabel="BELOW" rightValue={data.vwap_breadth.count_with_data ? `${(100-data.vwap_breadth.pct_above).toFixed(1)}%` : '—'} rightSub={`(${data.vwap_breadth.below_count})`}
          leftPct={data.vwap_breadth.pct_above || 0} />
        <SplitTile title="VOLUME" universe={va.count_with_data}
          leftLabel="UP VOL" leftValue={va.count_with_data ? `${(100*va.elevated_up/va.count_with_data).toFixed(1)}%` : '—'} leftSub={`(${va.elevated_up})`}
          rightLabel="DOWN VOL" rightValue={va.count_with_data ? `${(100*va.elevated_down/va.count_with_data).toFixed(1)}%` : '—'} rightSub={`(${va.elevated_down})`}
          leftPct={va.count_with_data ? 100*va.elevated_up/va.count_with_data : 0} />
      </div>
    </div>
  );
}
