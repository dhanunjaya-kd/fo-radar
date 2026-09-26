import { useState } from 'react';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { formatIndianCurrency, pickSeriesUnit, formatAxisTick, formatPercent, formatRatio } from '../utils/indianNumberFormat';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Sep 24 2026: Fundamental Research module -- new isolated app,
// separate sidebar entry, matches the existing dark-dashboard visual
// language already established across GammaStrategy.jsx/MarketPulse.jsx
// (slate-900/40 cards, slate-700/40 borders, emerald/rose/amber accent
// system) rather than a new visual identity -- this is a new page
// inside an existing product, not a standalone brand.
//
// Sep 26 2026: fmtInr/fmtPct/fmtNum below replaced with the shared,
// tested Indian number formatter (utils/indianNumberFormat.js) -- was
// showing raw unformatted rupee figures wide enough to get clipped on
// chart y-axes (confirmed from real screenshots: "0000000000"-style
// truncated labels), which is what made correctly-computed data look
// broken. fmtInr/fmtNum kept as thin aliases so the many existing
// call sites below don't all need renaming.

const SOURCE_LABEL = { bharatstock: 'BharatStock', screener: 'Screener.in', fyers: 'Fyers', calculated: 'Calculated', news: 'News', company_ir: 'Company IR', yfinance: 'Yahoo Finance' };

function fmtInr(n) {
  return formatIndianCurrency(n);
}
function fmtPct(n) {
  return formatPercent(n);
}
function fmtNum(n, d = 2) {
  if (n == null) return '—';
  const num = typeof n === 'string' ? parseFloat(n) : n;
  if (!Number.isFinite(num)) return '—';
  return num.toFixed(d);
}

function SourceTag({ source }) {
  if (!source) return null;
  return <span className="text-[9px] text-slate-500 bg-slate-800/60 px-1.5 py-0.5 rounded">{SOURCE_LABEL[source] || source}</span>;
}

function SectionCard({ title, children, right }) {
  return (
    <div className="rounded-lg bg-slate-900/40 border border-slate-700/40 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        {right}
      </div>
      {children}
    </div>
  );
}

function StatBox({ label, value, sub, source }) {
  return (
    <div className="rounded-lg bg-slate-900/60 border border-slate-700/30 p-3">
      <div className="text-[10px] text-slate-500 mb-1">{label}</div>
      <div className="text-base font-semibold text-white">{value}</div>
      {sub && <div className="text-[10px] text-slate-400 mt-0.5">{sub}</div>}
      {source && <div className="mt-1"><SourceTag source={source} /></div>}
    </div>
  );
}

function TrendChart({ data, dataKey, label, color = '#34d399' }) {
  if (!data || data.length < 2) {
    return <div className="text-xs text-slate-500 py-8 text-center">Not enough periods to chart a trend yet.</div>;
  }
  // Sep 26 2026 fix: this is the exact chart that showed clipped,
  // unreadable y-axis labels in real screenshots ("0000000000") --
  // raw rupee values (e.g. 1420943000000) are simply too wide for the
  // axis label space. Picking one consistent Cr/L unit for this
  // series and formatting both the axis ticks and the tooltip through
  // it fixes the truncation and makes the number actually readable,
  // without touching the underlying data value at all.
  const unit = pickSeriesUnit(data.map(d => d[dataKey]));
  return (
    <ResponsiveContainer width="100%" height={180}>
      <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.3} />
        <XAxis dataKey="period" tick={{ fontSize: 10, fill: '#94a3b8' }} />
        <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={v => formatAxisTick(v, unit)} width={56} />
        <Tooltip
          contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
          labelStyle={{ color: '#e2e8f0' }}
          formatter={(value) => [formatIndianCurrency(value), label]}
        />
        <Line type="monotone" dataKey={dataKey} name={label} stroke={color} strokeWidth={2} dot={{ r: 3 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

function OwnershipBar({ ownership }) {
  const promoter = parseFloat(ownership.promoter_pct) || 0;
  const fii = parseFloat(ownership.fii_pct) || 0;
  const dii = parseFloat(ownership.dii_pct) || 0;
  const mf = parseFloat(ownership.mutual_fund_pct) || 0;
  // Sep 25 2026 fix: confirmed from real data (promoter + public summed to
  // ~100% on their own, e.g. 72.59 + 27.29 = 99.88 for WIPRO) that
  // BharatStock's "Public" field already INCLUDES FII/DII/MF as subsets --
  // they're not separate, additive slices. The previous version stacked
  // all four independently and overflowed past 100% (118.5% seen live on
  // OFSS). Now: only Promoter vs Public are drawn as the two real,
  // mutually-exclusive bar segments; FII/DII/MF are shown as a labeled
  // breakdown of what's inside "Public," not additional bar width.
  const publicTotal = parseFloat(ownership.public_pct) || (promoter ? Math.max(0, 100 - promoter) : 0);
  const publicOther = Math.max(0, publicTotal - fii - dii - mf);

  const barData = [
    { name: 'Promoter', value: promoter, color: '#34d399' },
    { name: 'Public', value: publicTotal, color: '#475569' },
  ].filter(d => d.value > 0);
  if (!barData.length) return <div className="text-xs text-slate-500">No shareholding data available.</div>;

  return (
    <div>
      <div className="flex h-3 rounded-full overflow-hidden mb-2">
        {barData.map(d => <div key={d.name} style={{ width: `${d.value}%`, backgroundColor: d.color }} title={`${d.name}: ${d.value.toFixed(1)}%`} />)}
      </div>
      <div className="flex flex-wrap gap-3 text-[11px] mb-2">
        {barData.map(d => (
          <span key={d.name} className="flex items-center gap-1 text-slate-300">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: d.color }} />
            {d.name} {d.value.toFixed(1)}%
          </span>
        ))}
      </div>
      {(fii > 0 || dii > 0 || mf > 0) && (
        <div className="text-[10px] text-slate-500 pl-1 border-l border-slate-700/50">
          Within Public: FII {fii.toFixed(1)}% · DII {dii.toFixed(1)}% · MF {mf.toFixed(1)}%{publicOther > 0.1 ? ` · Other ${publicOther.toFixed(1)}%` : ''}
        </div>
      )}
    </div>
  );
}

const SENTIMENT_STYLE = { positive: 'text-emerald-400 bg-emerald-500/10', negative: 'text-rose-400 bg-rose-500/10', neutral: 'text-slate-400 bg-slate-500/10' };

function NewsItem({ item }) {
  return (
    <a href={item.url} target="_blank" rel="noreferrer" className="block rounded-lg bg-slate-900/40 border border-slate-700/30 p-3 hover:border-slate-600/50 transition-colors">
      <div className="flex items-start justify-between gap-2 mb-1">
        <span className="text-xs text-white font-medium leading-snug">{item.headline}</span>
        {item.sentiment && <span className={`shrink-0 text-[9px] px-1.5 py-0.5 rounded ${SENTIMENT_STYLE[item.sentiment] || SENTIMENT_STYLE.neutral}`}>{item.sentiment}</span>}
      </div>
      <div className="text-[10px] text-slate-500">{item.news_source}{item.published_at ? ` · ${new Date(item.published_at).toLocaleDateString('en-IN')}` : ''}</div>
    </a>
  );
}

function RiskItem({ risk }) {
  return (
    <div className="rounded-lg bg-slate-900/40 border border-amber-700/20 p-3">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs font-semibold text-amber-400">{risk.risk}</span>
      </div>
      <div className="text-[11px] text-slate-300 mb-1">{risk.evidence}</div>
      <div className="text-[10px] text-slate-500">{risk.potential_relevance}</div>
      <div className="mt-1"><SourceTag source={risk.source} /></div>
    </div>
  );
}

function WhatChanged({ data }) {
  if (!data) return null;
  if (data.status === 'first_snapshot') {
    return <div className="text-xs text-slate-500 italic">{data.message}</div>;
  }
  const entries = Object.entries(data);
  if (!entries.length) return <div className="text-xs text-slate-500">No tracked metric changed since the last snapshot.</div>;
  return (
    <div className="space-y-2">
      {entries.map(([metric, change]) => (
        <div key={metric} className="flex items-center justify-between text-xs">
          <span className="text-slate-300 capitalize">{metric.replace(/_/g, ' ')}</span>
          <span className="flex items-center gap-2">
            <span className="text-slate-500">{fmtNum(change.previous)} → {fmtNum(change.current)}</span>
            <span className={change.change >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{fmtPct(change.change_pct)}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

function TwoSeriesBarChart({ data, keyA, labelA, colorA, keyB, labelB, colorB }) {
  if (!data || data.length < 1) {
    return <div className="text-xs text-slate-500 py-8 text-center">Not enough periods to chart yet.</div>;
  }
  const unit = pickSeriesUnit(data.flatMap(d => [d[keyA], d[keyB]]));
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.3} />
        <XAxis dataKey="period" tick={{ fontSize: 10, fill: '#94a3b8' }} />
        <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={v => formatAxisTick(v, unit)} width={56} />
        <Tooltip
          contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
          labelStyle={{ color: '#e2e8f0' }}
          formatter={(value, name) => [formatIndianCurrency(value), name]}
        />
        <Bar dataKey={keyA} name={labelA} fill={colorA} radius={[3, 3, 0, 0]} />
        <Bar dataKey={keyB} name={labelB} fill={colorB} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function SegmentBreakdown({ segments, reportedTotalRevenue }) {
  if (!segments || !segments.length) return <div className="text-xs text-slate-500">No segment data available.</div>;
  // Sep 25 2026: segments come back per-fiscal-period from the backend
  // (one row per segment per year) -- show only the LATEST period's
  // breakdown here, not every year mixed together.
  const latestPeriod = segments.reduce((max, s) => (s.fiscal_period > max ? s.fiscal_period : max), segments[0].fiscal_period);
  const latest = segments.filter(s => s.fiscal_period === latestPeriod);
  const segmentSum = latest.reduce((sum, s) => sum + (parseFloat(s.segment_revenue) || 0), 0);

  // Sep 26 2026: real bug found and fixed -- proven with actual GAIL
  // numbers, the largest single segment alone (₹1,55,918.52 Cr)
  // exceeded the company's entire REPORTED total revenue
  // (₹1,42,094.30 Cr). Percentages below were already computed
  // against the segment sum (not company total), which is technically
  // fine -- but nothing ever told the reader that, or warned when the
  // segment sum itself doesn't reconcile with the real reported
  // total. Most likely real cause, not a code bug: segment figures
  // for gas-trading companies like GAIL are often reported GROSS of
  // inter-segment sales (segments sell to each other internally),
  // while consolidated revenue is NET of those eliminations -- a
  // real, known accounting pattern, not fabricated data. Surfaced
  // honestly here instead of silently implying "88% of the company."
  const reconciles = reportedTotalRevenue != null && Math.abs(segmentSum - reportedTotalRevenue) / reportedTotalRevenue < 0.05;

  return (
    <div>
      <div className="text-[10px] text-slate-500 mb-2">{latestPeriod} · % shown is each segment's share of the segment total shown below, not of company revenue</div>
      <div className="space-y-2">
        {latest.map((s, i) => {
          const rev = parseFloat(s.segment_revenue) || 0;
          const pct = segmentSum ? (rev / segmentSum * 100) : 0;
          return (
            <div key={i}>
              <div className="flex items-center justify-between text-[11px] mb-1">
                <span className="text-slate-300">{s.segment_name}</span>
                <span className="text-slate-400">{fmtInr(s.segment_revenue)} · {pct.toFixed(0)}%</span>
              </div>
              <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                <div className="h-full bg-emerald-500/70 rounded-full" style={{ width: `${pct}%` }} />
              </div>
            </div>
          );
        })}
      </div>
      <div className="text-[10px] text-slate-500 mt-3 pt-2 border-t border-slate-800">
        Segment total: {fmtInr(segmentSum)}
        {reportedTotalRevenue != null && !reconciles && (
          <span className="text-amber-500/80"> — does not reconcile with reported consolidated revenue ({fmtInr(reportedTotalRevenue)}). Segment figures may be reported gross of inter-segment sales; treat as directional, not exact company-wide share.</span>
        )}
      </div>
    </div>
  );
}

function ScenarioCard({ title, scenario, tone }) {
  const toneClass = { bull: 'border-emerald-700/30 text-emerald-400', base: 'border-slate-700/30 text-slate-300', bear: 'border-rose-700/30 text-rose-400' }[tone];
  if (!scenario) return null;
  return (
    <div className={`rounded-lg bg-slate-900/40 border p-3 ${toneClass.split(' ')[0]}`}>
      <div className={`text-xs font-semibold mb-2 ${toneClass.split(' ')[1]}`}>{title}</div>
      {scenario.assumptions?.length > 0 && (
        <ul className="text-[11px] text-slate-300 space-y-1 mb-2 list-disc list-inside">
          {scenario.assumptions.map((a, i) => <li key={i}>{a}</li>)}
        </ul>
      )}
      {scenario.metrics_to_monitor?.length > 0 && (
        <div className="text-[10px] text-slate-500">Watch: {scenario.metrics_to_monitor.join(', ')}</div>
      )}
      {scenario.invalidation_triggers?.length > 0 && (
        <div className="text-[10px] text-slate-500 mt-1">Invalidated if: {scenario.invalidation_triggers.join('; ')}</div>
      )}
    </div>
  );
}

export default function ResearchDashboard() {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [primarySource, setPrimarySource] = useState(null);

  const runResearch = async (symbol, forceRefresh) => {
    if (!symbol.trim()) return;
    setLoading(true);
    setError(null);
    try {
      if (!forceRefresh) {
        const existing = await fetch(`${API_BASE}/api/research/company/${symbol.trim().toUpperCase()}/report/`);
        if (existing.ok) {
          const data = await existing.json();
          setSnapshot(data);
          setPrimarySource(null);
          setLoading(false);
          return;
        }
      }
      const res = await fetch(`${API_BASE}/api/research/company/${symbol.trim().toUpperCase()}/refresh/`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Research failed for this symbol.');
      setSnapshot(data.snapshot);
      setPrimarySource(data.primary_source);
    } catch (e) {
      setError(e.message || 'Something went wrong.');
      setSnapshot(null);
    } finally {
      setLoading(false);
    }
  };

  const financials = snapshot?.financials ? [...snapshot.financials].reverse() : [];
  const chartData = financials.map(f => ({
    period: f.fiscal_year, revenue: f.revenue ? parseFloat(f.revenue) : null,
    pat: f.pat ? parseFloat(f.pat) : null, ebitda: f.ebitda ? parseFloat(f.ebitda) : null,
    eps: f.eps ? parseFloat(f.eps) : null,
    ebitda_margin_pct: f.ebitda_margin_pct ? parseFloat(f.ebitda_margin_pct) : null,
    pat_margin_pct: f.pat_margin_pct ? parseFloat(f.pat_margin_pct) : null,
  }));
  const balanceSheets = snapshot?.balance_sheets ? [...snapshot.balance_sheets].reverse() : [];
  const debtCashData = balanceSheets.map(b => ({
    period: b.fiscal_year, debt: b.total_debt ? parseFloat(b.total_debt) : null, cash: b.cash ? parseFloat(b.cash) : null,
  }));
  const cashFlows = snapshot?.cash_flows ? [...snapshot.cash_flows].reverse() : [];
  const ocfFcfData = cashFlows.map(c => ({
    period: c.fiscal_year, ocf: c.operating_cash_flow ? parseFloat(c.operating_cash_flow) : null,
    fcf: c.free_cash_flow ? parseFloat(c.free_cash_flow) : null,
  }));
  const latest = financials[financials.length - 1];
  const bs = snapshot?.balance_sheets?.[0];
  const cf = snapshot?.cash_flows?.[0];
  const report = snapshot?.report;

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-slate-900/40 border border-slate-700/40 p-4">
        <h2 className="text-base font-semibold text-white mb-3">Fundamental Research</h2>
        <div className="flex gap-2">
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && runResearch(query, false)}
            placeholder="RELIANCE, TCS, HDFCBANK..."
            className="flex-1 bg-slate-950/60 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-slate-500"
          />
          <button
            onClick={() => runResearch(query, false)}
            disabled={loading}
            className="px-4 py-2 rounded-lg bg-emerald-600/20 border border-emerald-600/40 text-emerald-400 text-sm font-medium hover:bg-emerald-600/30 transition-colors disabled:opacity-50"
          >
            {loading ? 'Researching…' : 'Research'}
          </button>
        </div>
        {error && <div className="text-xs text-rose-400 mt-2">{error}</div>}
      </div>

      {snapshot && (
        <>
          <div className="rounded-lg bg-slate-900/40 border border-slate-700/40 p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-bold text-white">{snapshot.company.company_name || snapshot.company.symbol}</h2>
                  <span className="text-xs text-slate-500">{snapshot.company.symbol}</span>
                </div>
                <div className="text-xs text-slate-400 mt-1">{snapshot.company.sector} · {snapshot.company.industry} · {snapshot.company.exchange}</div>
              </div>
              <div className="text-right">
                {primarySource && <SourceTag source={primarySource} />}
                <button onClick={() => runResearch(snapshot.company.symbol, true)} className="block mt-2 text-[10px] text-slate-500 hover:text-slate-300 underline">Refresh</button>
              </div>
            </div>
            {report?.business_overview && <p className="text-xs text-slate-300 mt-3 leading-relaxed">{report.business_overview}</p>}
          </div>

          <SectionCard title="Financial Snapshot">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              <StatBox label={`Revenue (${latest?.fiscal_year || '—'})`} value={fmtInr(latest?.revenue)} sub={latest?.revenue_growth_yoy_pct != null ? `${fmtPct(latest.revenue_growth_yoy_pct)} YoY` : null} source={latest?.source} />
              <StatBox label="PAT" value={fmtInr(latest?.pat)} sub={latest?.pat_growth_yoy_pct != null ? `${fmtPct(latest.pat_growth_yoy_pct)} YoY` : null} source={latest?.source} />
              <StatBox label="EBITDA Margin" value={latest?.ebitda_margin_pct != null ? `${fmtNum(latest.ebitda_margin_pct)}%` : '—'} source="calculated" />
              <StatBox label="ROE" value={latest?.roe_pct != null ? `${fmtNum(latest.roe_pct)}%` : '—'} source="calculated" />
            </div>
            <TrendChart data={chartData} dataKey="revenue" label="Revenue" color="#34d399" />
            <div className="grid md:grid-cols-3 gap-3 mt-4">
              <div>
                <div className="text-[10px] text-slate-500 mb-1">PAT</div>
                <TrendChart data={chartData} dataKey="pat" label="PAT" color="#60a5fa" />
              </div>
              <div>
                <div className="text-[10px] text-slate-500 mb-1">EBITDA</div>
                <TrendChart data={chartData} dataKey="ebitda" label="EBITDA" color="#fbbf24" />
              </div>
              <div>
                <div className="text-[10px] text-slate-500 mb-1">EPS</div>
                <TrendChart data={chartData} dataKey="eps" label="EPS" color="#a78bfa" />
              </div>
            </div>
            <div className="mt-4">
              <div className="text-[10px] text-slate-500 mb-1">Margin Trend</div>
              <ResponsiveContainer width="100%" height={160}>
                <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.3} />
                  <XAxis dataKey="period" tick={{ fontSize: 10, fill: '#94a3b8' }} />
                  <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={v => `${v}%`} width={40} />
                  <Tooltip
                    contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 6, fontSize: 11 }}
                    labelStyle={{ color: '#e2e8f0' }}
                    formatter={(value, name) => [`${value.toFixed(2)}%`, name]}
                  />
                  <Line type="monotone" dataKey="ebitda_margin_pct" name="EBITDA Margin %" stroke="#fbbf24" strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="pat_margin_pct" name="PAT Margin %" stroke="#60a5fa" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </SectionCard>

          <div className="grid md:grid-cols-2 gap-4">
            <SectionCard title="Debt vs Cash">
              <TwoSeriesBarChart data={debtCashData} keyA="debt" labelA="Total Debt" colorA="#f87171" keyB="cash" labelB="Cash" colorB="#34d399" />
            </SectionCard>
            <SectionCard title="Operating CF vs Free Cash Flow">
              <TwoSeriesBarChart data={ocfFcfData} keyA="ocf" labelA="Operating CF" colorA="#60a5fa" keyB="fcf" labelB="Free Cash Flow" colorB="#34d399" />
            </SectionCard>
          </div>

          {snapshot.segments?.length > 0 && (
            <SectionCard title="Segment Revenue">
              <SegmentBreakdown segments={snapshot.segments} reportedTotalRevenue={latest?.revenue ? parseFloat(latest.revenue) : null} />
            </SectionCard>
          )}

          <div className="grid md:grid-cols-2 gap-4">
            <SectionCard title="Balance Sheet">
              {bs ? (
                <div className="grid grid-cols-2 gap-3">
                  <StatBox label="Total Debt" value={fmtInr(bs.total_debt)} source={bs.source} />
                  <StatBox label="Cash" value={fmtInr(bs.cash)} source={bs.source} />
                  <StatBox label="Debt/Equity" value={formatRatio(bs.debt_equity)} source="calculated" />
                  <StatBox label="Current Ratio" value={formatRatio(bs.current_ratio)} source="calculated" />
                </div>
              ) : <div className="text-xs text-slate-500">N/A — no balance sheet data available.</div>}
            </SectionCard>

            <SectionCard title="Cash Flow">
              {cf ? (
                <div className="grid grid-cols-2 gap-3">
                  <StatBox label="Operating CF" value={fmtInr(cf.operating_cash_flow)} source={cf.source} />
                  <StatBox label="Free Cash Flow" value={fmtInr(cf.free_cash_flow)} source="calculated" />
                  <StatBox label="CFO/PAT" value={formatRatio(cf.cfo_to_pat)} source="calculated" />
                  <StatBox label="Capex Intensity" value={cf.capex_intensity_pct != null ? `${fmtNum(cf.capex_intensity_pct)}%` : '—'} source="calculated" />
                </div>
              ) : <div className="text-xs text-slate-500">N/A — no cash flow data available.</div>}
            </SectionCard>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <SectionCard title="Ownership">
              {snapshot.ownership ? (
                <>
                  <OwnershipBar ownership={snapshot.ownership} />
                  {snapshot.ownership.promoter_pledge_pct > 0 && (
                    <div className="mt-3 text-[11px] text-amber-400">Promoter pledge: {fmtNum(snapshot.ownership.promoter_pledge_pct)}%</div>
                  )}
                  <div className="mt-2"><SourceTag source={snapshot.ownership.source} /></div>
                </>
              ) : <div className="text-xs text-slate-500">N/A — no shareholding data available.</div>}
            </SectionCard>

            <SectionCard title="Valuation">
              {snapshot.valuation ? (
                <div className="grid grid-cols-2 gap-3">
                  <StatBox label="P/E" value={formatRatio(snapshot.valuation.pe)} source={snapshot.valuation.source} />
                  <StatBox label="P/B" value={formatRatio(snapshot.valuation.pb)} source={snapshot.valuation.source} />
                  <StatBox label="52W Range" value={`${fmtInr(snapshot.valuation.week_52_low)} – ${fmtInr(snapshot.valuation.week_52_high)}`} />
                  <StatBox label="From 52W High" value={fmtPct(snapshot.valuation.distance_from_52w_high_pct)} />
                </div>
              ) : <div className="text-xs text-slate-500">N/A — no valuation data available.</div>}
            </SectionCard>
          </div>

          {report?.risks_json?.length > 0 && (
            <SectionCard title="Risks">
              <div className="grid md:grid-cols-2 gap-3">
                {report.risks_json.map((r, i) => <RiskItem key={i} risk={r} />)}
              </div>
            </SectionCard>
          )}

          {(report?.bull_case_json || report?.base_case_json || report?.bear_case_json) && (
            <SectionCard title="Scenarios — labeled assumptions, not forecasts">
              <div className="grid md:grid-cols-3 gap-3">
                <ScenarioCard title="Bull Case" scenario={report.bull_case_json} tone="bull" />
                <ScenarioCard title="Base Case" scenario={report.base_case_json} tone="base" />
                <ScenarioCard title="Bear Case" scenario={report.bear_case_json} tone="bear" />
              </div>
            </SectionCard>
          )}

          {snapshot.news_items?.length > 0 && (
            <SectionCard title="Recent News">
              <div className="space-y-2">
                {snapshot.news_items.map((n, i) => <NewsItem key={i} item={n} />)}
              </div>
            </SectionCard>
          )}

          {report?.what_changed_json && (
            <SectionCard title="What Changed Since Last Research">
              <WhatChanged data={report.what_changed_json} />
            </SectionCard>
          )}

          {report?.governance_notes && (
            <SectionCard title="Management & Governance">
              <p className="text-xs text-slate-300 leading-relaxed">{report.governance_notes}</p>
            </SectionCard>
          )}

          <div className="text-[10px] text-slate-600 text-center pb-2">
            Snapshot: {snapshot.snapshot_date} · Generated {report?.generated_at ? new Date(report.generated_at).toLocaleString('en-IN') : '—'}
          </div>
        </>
      )}

      {!snapshot && !loading && !error && (
        <div className="text-center py-12 text-sm text-slate-500">Search a stock symbol above to generate a research report.</div>
      )}
    </div>
  );
}
