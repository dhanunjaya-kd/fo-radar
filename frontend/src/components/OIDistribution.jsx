import { useEffect, useState } from 'react';
import { useTone } from './ThemeContext';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Aug 28 2026: layout math verified in test_oi_distribution.js before
// this component was written -- correct scaling to the true global
// max, no overlapping strike groups, and Max Pain correctly snaps to
// the nearest real strike rather than erroring when it falls between
// listed strikes.
function computeOIDistributionLayout(rows, maxPain, atmStrike, width, height) {
  if (rows.length === 0) return null;
  const maxOi = Math.max(...rows.flatMap(r => [r.ce_oi || 0, r.pe_oi || 0]), 1);
  const barGroupWidth = width / rows.length;
  const barWidth = barGroupWidth * 0.35;

  const bars = rows.map((r, i) => {
    const groupX = i * barGroupWidth;
    const ceHeight = ((r.ce_oi || 0) / maxOi) * height;
    const peHeight = ((r.pe_oi || 0) / maxOi) * height;
    return {
      strike: r.strike,
      ceX: groupX + barGroupWidth * 0.15, ceY: height - ceHeight, ceHeight,
      peX: groupX + barGroupWidth * 0.55, peY: height - peHeight, peHeight,
      barWidth, groupX, groupWidth: barGroupWidth,
    };
  });

  const strikeToX = (target) => {
    if (target == null) return null;
    const closestIdx = rows.reduce((closestI, r, i) =>
      Math.abs(r.strike - target) < Math.abs(rows[closestI].strike - target) ? i : closestI, 0);
    return closestIdx * barGroupWidth + barGroupWidth / 2;
  };

  return { bars, maxPainX: strikeToX(maxPain), atmX: strikeToX(atmStrike), maxOi };
}

function fmtOi(n) {
  if (n == null) return '—';
  return `${(n / 100000).toFixed(1)}L`;
}

function fmtVol(n) {
  if (n == null) return '—';
  // Sep 3 2026: real bug, visible directly in a real screenshot --
  // "99794K" / "135915K". Volume can genuinely run into the millions
  // for NIFTY, and this never rolled over past K, so it just kept
  // printing more and more digits instead of switching units. Now
  // escalates the same way fmtOi already does (K -> L), so large
  // volumes read the same way large OI already does elsewhere on this
  // exact chart.
  if (n >= 100000) return `${(n / 100000).toFixed(1)}L`;
  return n >= 1000 ? `${(n / 1000).toFixed(0)}K` : String(n);
}

// Sep 3 2026: per-strike PCR + sentiment -- same exact formula and
// thresholds already built and tested in StrikeOIChart.jsx (duplicated
// here rather than imported, matching this project's own established
// preference for small duplicated logic over a shared-file dependency
// -- see IconBell in App.jsx for the precedent).
function computeStrikePcr(ceOi, peOi) {
  if (!ceOi || !peOi || ceOi <= 0) return null;
  return peOi / ceOi;
}
function pcrSentimentLabel(pcr) {
  if (pcr == null) return { label: '—', color: 'text-slate-400' };
  if (pcr > 1.05) return { label: 'Bullish', color: 'text-emerald-400' };
  if (pcr < 0.95) return { label: 'Bearish', color: 'text-rose-400' };
  return { label: 'Neutral', color: 'text-amber-400' };
}

// Sep 3 2026: pulled out as its own pure function (was inline in the
// component before) -- now also carries ce_volume/pe_volume/ce_ltp/
// pe_ltp/ce_oi_chg/pe_oi_chg/ce_iv/pe_iv/ce_delta/pe_delta through,
// which the backend was already returning in ceData/peData (same raw
// fields Analytics.jsx already maps for its own table -- oi_chg_pct,
// iv, delta) but this component was silently dropping, keeping only
// `oi`. Real data that already existed, just never reached this
// component's own row shape -- not a new backend call.
function mergeOIRows(ceData, peData) {
  const byStrike = {};
  let totalCeOi = 0, totalPeOi = 0;
  for (const c of ceData || []) {
    byStrike[c.strike] = byStrike[c.strike] || { strike: c.strike, ce_oi: 0, pe_oi: 0 };
    byStrike[c.strike].ce_oi = c.oi || 0;
    byStrike[c.strike].ce_volume = c.volume ?? null;
    byStrike[c.strike].ce_ltp = c.ltp ?? null;
    byStrike[c.strike].ce_oi_chg = c.oi_chg_pct ?? null;
    byStrike[c.strike].ce_oi_chg_abs = c.oi_chg ?? null;
    byStrike[c.strike].ce_iv = c.iv ?? null;
    byStrike[c.strike].ce_delta = c.delta ?? null;
    totalCeOi += c.oi || 0;
  }
  for (const p of peData || []) {
    byStrike[p.strike] = byStrike[p.strike] || { strike: p.strike, ce_oi: 0, pe_oi: 0 };
    byStrike[p.strike].pe_oi = p.oi || 0;
    byStrike[p.strike].pe_volume = p.volume ?? null;
    byStrike[p.strike].pe_ltp = p.ltp ?? null;
    byStrike[p.strike].pe_oi_chg = p.oi_chg_pct ?? null;
    byStrike[p.strike].pe_oi_chg_abs = p.oi_chg ?? null;
    byStrike[p.strike].pe_iv = p.iv ?? null;
    byStrike[p.strike].pe_delta = p.delta ?? null;
    totalPeOi += p.oi || 0;
  }
  const rows = Object.values(byStrike).sort((a, b) => a.strike - b.strike);
  return { rows, totalCeOi, totalPeOi };
}

const INDICES = ['NIFTY', 'BANKNIFTY', 'SENSEX'];
const EXPIRIES = [['current', 'Nearest'], ['next', 'Next'], ['monthly', 'Monthly']];
const fmtPrice = (n, d = 0) => (n == null ? '—' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: d }));
const fmtSigned = (n) => (n == null ? '—' : `${n >= 0 ? '+' : '−'}${fmtOi(Math.abs(n))}`);

// What the chain itself says -- every number below is computed from the strikes already on screen
// (nothing is forecast): the biggest OI strikes on each side are the "walls", the biggest fresh additions
// are where writers are adding today, and the ATM straddle is the market's priced-in move to expiry.
function computeInsights(rows, data) {
  const top = (key, n = 3) => [...rows].filter((r) => r[key] > 0).sort((a, b) => b[key] - a[key]).slice(0, n);
  const fresh = (key) => [...rows].filter((r) => (r[key] ?? 0) > 0).sort((a, b) => b[key] - a[key])[0] || null;
  const spot = data?.spot ?? null;
  const straddle = data?.atmStraddlePrice ?? null;
  return {
    callWalls: top('ce_oi'),
    putWalls: top('pe_oi'),
    freshCall: fresh('ce_oi_chg_abs'),
    freshPut: fresh('pe_oi_chg_abs'),
    expectedMove: straddle != null ? straddle : null,
    expectedMovePct: straddle != null && spot ? (straddle / spot) * 100 : null,
  };
}

function Tile({ label, value, sub, tone }) {
  return (
    <div className="rounded-lg border border-slate-700/50 bg-slate-900/40 px-3 py-2 min-w-0">
      <div className="text-[9px] tracking-wide text-slate-500 uppercase">{label}</div>
      <div className={`text-base font-bold tabular-nums ${tone || 'text-white'}`}>{value}</div>
      {sub && <div className="text-[10px] text-slate-500 truncate">{sub}</div>}
    </div>
  );
}

function WallList({ title, tone, rows, valueKey, chgKey, spot }) {
  const max = Math.max(...rows.map((r) => r[valueKey]), 1);
  return (
    <div>
      <div className={`text-[10px] font-semibold uppercase tracking-wide mb-1.5 ${tone}`}>{title}</div>
      {rows.length === 0 && <div className="text-[11px] text-slate-500">No data</div>}
      <div className="space-y-1.5">
        {rows.map((r, i) => {
          const chg = r[chgKey];
          return (
            <div key={r.strike} className="flex items-center gap-2 text-[11px]">
              <span className="w-5 text-slate-500">#{i + 1}</span>
              <span className="w-16 font-semibold text-white tabular-nums">{r.strike.toLocaleString('en-IN')}</span>
              <div className="flex-1 h-1.5 rounded-full bg-slate-800 overflow-hidden"><div className={`h-full rounded-full ${tone.includes('rose') ? 'bg-rose-400' : 'bg-emerald-400'}`} style={{ width: `${(r[valueKey] / max) * 100}%` }} /></div>
              <span className="w-12 text-right text-slate-300 tabular-nums">{fmtOi(r[valueKey])}</span>
              <span className={`w-14 text-right tabular-nums ${chg == null ? 'text-slate-500' : chg >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{fmtSigned(chg)}</span>
              {spot != null && <span className="hidden sm:block w-14 text-right text-slate-500 tabular-nums">{(((r.strike - spot) / spot) * 100).toFixed(1)}%</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function OIDistribution() {
  const t = useTone();
  const [selected, setSelected] = useState('NIFTY');
  const [expiry, setExpiry] = useState('current');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hoverIdx, setHoverIdx] = useState(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);
    const fetchData = async () => {
      try {
        // Same /api/option-analytics/<symbol>/ endpoint already fixed
        // earlier tonight to support NIFTY/BANKNIFTY -- no new backend
        // work needed for this panel at all.
        // 'current' is the endpoint's default, so it is requested WITHOUT a query string: after the close the
        // server replays the last session's snapshot keyed by the exact URL, and the plain URL is the one that
        // has always been saved (adding ?expiry=current made after-hours requests miss it).
        const qs = expiry === 'current' ? '' : `?expiry=${expiry}`;
        const res = await fetch(`${API_BASE}/api/option-analytics/${selected}/${qs}`);
        const json = await res.json().catch(() => ({}));
        if (!res.ok) {
          if (json.error === 'market_closed_no_snapshot') {
            throw new Error(`Market is closed and there is no saved snapshot for ${selected}${expiry === 'current' ? '' : ` (${expiry} expiry)`} from the last session. Open this view once while the market is live and it will be available after the close.`);
          }
          throw new Error(json.error || json.message || 'HTTP ' + res.status);
        }
        if (mounted) {
          if (json.live === false) {
            setError(json.error || 'No live data available right now.');
            setData(null);
          } else {
            setData(json);
          }
        }
      } catch (err) {
        if (mounted) { console.error('OI distribution fetch error:', err); setError(err.message); }
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => { mounted = false; clearInterval(interval); };
  }, [selected, expiry]);

  const WIDTH = 700, HEIGHT = 220;

  // Merge ceData/peData (each a flat list of {strike, oi, ...}) into
  // one row per strike -- see mergeOIRows() above.
  let rows = [];
  let totalCeOi = 0, totalPeOi = 0;
  if (data) {
    const merged = mergeOIRows(data.ceData, data.peData);
    rows = merged.rows;
    totalCeOi = merged.totalCeOi;
    totalPeOi = merged.totalPeOi;
  }
  // Sep 9 2026: checks a few plausible field names since
  // /api/option-analytics/<symbol>/'s exact response shape for ATM
  // strike isn't confirmed in this session (unlike maxPain, which was
  // already being read successfully above) -- resolves to whichever
  // one is actually present, or null (marker just doesn't render,
  // same "never guess, mark unavailable" as everywhere else) if none
  // of them are.
  const atmStrike = data?.atmStrike ?? data?.atm_strike ?? data?.atm ?? null;
  const layout = rows.length > 0 ? computeOIDistributionLayout(rows, data?.maxPain, atmStrike, WIDTH, HEIGHT) : null;
  const totalOi = totalCeOi + totalPeOi;
  const insights = rows.length ? computeInsights(rows, data) : null;
  const pcrInfo = pcrSentimentLabel(data?.pcr ?? null);

  return (
    <div className="rounded-xl bg-slate-800/60 border border-slate-700/50 p-4">
      <div className="flex items-center justify-between gap-2 flex-wrap mb-3">
        <div>
          <h3 className="text-sm font-bold text-white">OI Distribution</h3>
          {data?.resolvedExpiryDate && <p className="text-[10px] text-slate-500 mt-0.5">Expiry {data.resolvedExpiryDate}{data.days_to_expiry != null ? ` · ${data.days_to_expiry}d` : ''} · 10 strikes either side of ATM</p>}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex gap-1 bg-slate-900/50 p-0.5 rounded-lg">
            {EXPIRIES.map(([k, label]) => (
              <button key={k} onClick={() => setExpiry(k)}
                className={`text-[11px] font-medium px-2.5 py-1 rounded-md transition-colors ${expiry === k ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'}`}>{label}</button>
            ))}
          </div>
          <div className="flex gap-1 bg-slate-900/50 p-0.5 rounded-lg">
            {INDICES.map((idx) => (
              <button key={idx} onClick={() => setSelected(idx)}
                className={`text-[11px] font-medium px-2.5 py-1 rounded-md transition-colors ${selected === idx ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'}`}>{idx}</button>
            ))}
          </div>
        </div>
      </div>

      {loading ? (
        <div className="h-56 rounded-lg bg-slate-900/30 animate-pulse" />
      ) : error || !layout ? (
        <div className="py-8 text-center">
          <p className="text-sm text-slate-500">{error || 'No live option chain available right now.'}</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-2 mb-4">
            <Tile label="Spot" value={fmtPrice(data.spot, 2)} sub={selected} />
            <Tile label="PCR (OI)" value={data.pcr != null ? Number(data.pcr).toFixed(2) : '—'} sub={`${pcrInfo.label}${data.pcrVolume != null ? ` · vol ${Number(data.pcrVolume).toFixed(2)}` : ''}`} tone={pcrInfo.color} />
            <Tile label="Max pain" value={fmtPrice(data.maxPain)} sub={data.maxPainDistPct != null ? `spot ${data.maxPainDistPct >= 0 ? '+' : ''}${data.maxPainDistPct}% from it` : null} tone="text-amber-400" />
            <Tile label="ATM IV" value={data.atmIv != null ? `${data.atmIv}%` : '—'} sub={atmStrike != null ? `strike ${fmtPrice(atmStrike)}` : null} />
            <Tile label="ATM straddle" value={data.atmStraddlePrice != null ? `₹${fmtPrice(data.atmStraddlePrice, 1)}` : '—'} sub={insights?.expectedMovePct != null ? `priced-in move ±${insights.expectedMovePct.toFixed(2)}%` : null} />
            <Tile label="Put wall (support)" value={fmtPrice(data.support)} sub={data.support != null && data.spot ? `${(((data.support - data.spot) / data.spot) * 100).toFixed(1)}% from spot` : null} tone="text-rose-400" />
            <Tile label="Call wall (resistance)" value={fmtPrice(data.resistance)} sub={data.resistance != null && data.spot ? `+${(((data.resistance - data.spot) / data.spot) * 100).toFixed(1)}% from spot` : null} tone="text-emerald-400" />
            <Tile label="OI change today" value={`CE ${fmtSigned(data.ceOiChg)}`} sub={`PE ${fmtSigned(data.peOiChg)}`} tone={data.peOiChg > data.ceOiChg ? 'text-emerald-400' : 'text-rose-400'} />
          </div>
          {data.oiBuildup && <p className="text-[11px] text-slate-400 mb-3">Positioning: <span className="font-semibold text-slate-200">{data.oiBuildup}</span></p>}

          <div className="flex items-center justify-center gap-6 mb-2 text-xs">
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm bg-emerald-500" />
              <span className="text-slate-400">Call OI</span>
              <span className="text-white font-medium">{fmtOi(totalCeOi)}</span>
              <span className="text-slate-500">({totalOi ? ((totalCeOi / totalOi) * 100).toFixed(0) : 0}%)</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm bg-rose-500" />
              <span className="text-slate-400">Put OI</span>
              <span className="text-white font-medium">{fmtOi(totalPeOi)}</span>
              <span className="text-slate-500">({totalOi ? ((totalPeOi / totalOi) * 100).toFixed(0) : 0}%)</span>
            </span>
          </div>

          <div className="relative">
            <svg viewBox={`0 0 ${WIDTH} ${HEIGHT + 20}`} className="w-full h-auto" style={{ maxHeight: HEIGHT + 20 }}>
              {layout.bars.map((b, i) => (
                <g key={b.strike}
                   onMouseEnter={() => setHoverIdx(i)}
                   onMouseLeave={() => setHoverIdx(null)}
                   style={{ cursor: 'pointer' }}>
                  <rect x={b.ceX} y={b.ceY} width={b.barWidth} height={b.ceHeight} fill={t('#34d399')}
                        opacity={hoverIdx === null || hoverIdx === i ? 0.85 : 0.3} />
                  <rect x={b.peX} y={b.peY} width={b.barWidth} height={b.peHeight} fill={t('#fb7185')}
                        opacity={hoverIdx === null || hoverIdx === i ? 0.85 : 0.3} />
                  {/* invisible full-height hit area -- easier to hover accurately than the thin bars alone */}
                  <rect x={b.groupX} y="0" width={b.groupWidth} height={HEIGHT} fill="transparent" />
                </g>
              ))}
              {layout.maxPainX != null && (
                <>
                  <line x1={layout.maxPainX} y1="0" x2={layout.maxPainX} y2={HEIGHT} stroke={t('#fbbf24')} strokeWidth="1.5" strokeDasharray="4,3" />
                  <text x={layout.maxPainX} y={HEIGHT + 14} textAnchor="middle" fill={t('#fbbf24')} fontSize="10">
                    Max Pain {data.maxPain?.toLocaleString('en-IN')}
                  </text>
                </>
              )}
              {layout.atmX != null && (
                <>
                  <line x1={layout.atmX} y1="0" x2={layout.atmX} y2={HEIGHT} stroke={t('#818cf8')} strokeWidth="1.5" strokeDasharray="4,3" />
                  <text x={layout.atmX} y="10" textAnchor="middle" fill={t('#818cf8')} fontSize="10">
                    ATM {atmStrike?.toLocaleString('en-IN')}
                  </text>
                </>
              )}
            </svg>

            {hoverIdx != null && rows[hoverIdx] && (() => {
              const r = rows[hoverIdx];
              const pcr = computeStrikePcr(r.ce_oi, r.pe_oi);
              const sentiment = pcrSentimentLabel(pcr);
              return (
                <div className="absolute top-1 left-1 bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-xs shadow-xl pointer-events-none min-w-[210px]">
                  <p className="text-white font-bold mb-1">Strike ₹{r.strike.toLocaleString('en-IN')}</p>
                  <p className="text-[9px] text-slate-500 mb-2">Bar height = OI below, not OI Chg %</p>

                  <p className="text-[9px] text-emerald-400 uppercase tracking-wide font-semibold mb-1">Call (CE)</p>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 mb-2">
                    <span className="text-slate-400">OI</span><span className="text-right text-slate-200">{fmtOi(r.ce_oi)}</span>
                    <span className="text-slate-400">LTP</span><span className="text-right text-slate-200">{r.ce_ltp != null ? `₹${r.ce_ltp}` : '—'}</span>
                    <span className="text-slate-400">OI Chg</span>
                    <span className={`text-right ${r.ce_oi_chg == null ? 'text-slate-200' : r.ce_oi_chg >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {r.ce_oi_chg != null ? `${r.ce_oi_chg.toFixed(1)}%` : '—'}
                    </span>
                    <span className="text-slate-400">Volume</span><span className="text-right text-slate-200">{fmtVol(r.ce_volume)}</span>
                    <span className="text-slate-400">IV</span><span className="text-right text-slate-200">{r.ce_iv != null ? `${r.ce_iv.toFixed(1)}%` : '—'}</span>
                    <span className="text-slate-400">Delta</span><span className="text-right text-slate-200">{r.ce_delta ?? '—'}</span>
                  </div>

                  <p className="text-[9px] text-rose-400 uppercase tracking-wide font-semibold mb-1">Put (PE)</p>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 mb-2">
                    <span className="text-slate-400">OI</span><span className="text-right text-slate-200">{fmtOi(r.pe_oi)}</span>
                    <span className="text-slate-400">LTP</span><span className="text-right text-slate-200">{r.pe_ltp != null ? `₹${r.pe_ltp}` : '—'}</span>
                    <span className="text-slate-400">OI Chg</span>
                    <span className={`text-right ${r.pe_oi_chg == null ? 'text-slate-200' : r.pe_oi_chg >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {r.pe_oi_chg != null ? `${r.pe_oi_chg.toFixed(1)}%` : '—'}
                    </span>
                    <span className="text-slate-400">Volume</span><span className="text-right text-slate-200">{fmtVol(r.pe_volume)}</span>
                    <span className="text-slate-400">IV</span><span className="text-right text-slate-200">{r.pe_iv != null ? `${r.pe_iv.toFixed(1)}%` : '—'}</span>
                    <span className="text-slate-400">Delta</span><span className="text-right text-slate-200">{r.pe_delta ?? '—'}</span>
                  </div>

                  <div className="flex items-center justify-between pt-1.5 border-t border-slate-700">
                    <span className="text-amber-400 font-semibold">PCR</span>
                    <span className="text-slate-200">
                      {pcr != null ? pcr.toFixed(2) : '—'} <span className={sentiment.color}>({sentiment.label})</span>
                    </span>
                  </div>
                </div>
              );
            })()}
          </div>
          <div className="flex justify-between text-[9px] text-slate-500 mt-1">
            <span>{layout.bars[0]?.strike.toLocaleString('en-IN')}</span>
            <span>{layout.bars[layout.bars.length - 1]?.strike.toLocaleString('en-IN')}</span>
          </div>

          {insights && (
            <div className="mt-5 pt-4 border-t border-slate-700/50">
              <div className="flex items-baseline justify-between mb-3">
                <h4 className="text-xs font-bold text-white">OI walls &amp; fresh positioning</h4>
                <span className="text-[10px] text-slate-500">colours match the chart: green = calls, red = puts · strike · OI · change today · distance from spot</span>
              </div>
              <div className="grid md:grid-cols-2 gap-x-8 gap-y-5">
                <WallList title="Call walls — resistance" tone="text-emerald-400" rows={insights.callWalls} valueKey="ce_oi" chgKey="ce_oi_chg_abs" spot={data.spot} />
                <WallList title="Put walls — support" tone="text-rose-400" rows={insights.putWalls} valueKey="pe_oi" chgKey="pe_oi_chg_abs" spot={data.spot} />
              </div>
              <div className="grid md:grid-cols-2 gap-3 mt-4">
                <div className="rounded-lg bg-slate-900/40 border border-slate-700/40 px-3 py-2 text-[11px] text-slate-400">
                  Biggest fresh <b className="text-emerald-400">call</b> addition: {insights.freshCall ? <span className="text-slate-200"><b>{insights.freshCall.strike.toLocaleString('en-IN')}</b> ({fmtSigned(insights.freshCall.ce_oi_chg_abs)}) — new writing caps the upside there</span> : <span className="text-slate-500">none today</span>}
                </div>
                <div className="rounded-lg bg-slate-900/40 border border-slate-700/40 px-3 py-2 text-[11px] text-slate-400">
                  Biggest fresh <b className="text-rose-400">put</b> addition: {insights.freshPut ? <span className="text-slate-200"><b>{insights.freshPut.strike.toLocaleString('en-IN')}</b> ({fmtSigned(insights.freshPut.pe_oi_chg_abs)}) — new writing supports the downside there</span> : <span className="text-slate-500">none today</span>}
                </div>
              </div>
              <p className="text-[10px] text-slate-600 mt-3">Read from the option chain on screen: walls are the strikes holding the most open interest, not predictions. The ATM straddle is what the market is pricing as the move to expiry.</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
