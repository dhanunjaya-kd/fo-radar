import React, { useEffect, useState } from 'react'
import { useSignals } from '../hooks/useSignals'

const API_BASE = import.meta.env.VITE_API_URL || '';

// Table layout matches the reference the user gave (compact rows, colored
// pill badges per column) -- but populated with REAL fields from the live
// signal (grade, OI confirmation, action). The reference's own columns
// (Rev YoY%, PAT YoY%, Pattern/Signal from quarterly earnings) need
// financial-statement data Fyers doesn't provide, so those specific
// fields aren't reproduced -- only the visual format is.
//
// Columns are tightened (padding, font size, icon-only OI/Signal pills
// below the `sm` breakpoint) so all 8 fit at phone widths (~360-430px)
// without the horizontal scroll the untightened version needed. The
// full word labels ("Confirmed", "BUY") return at `sm:` and up where
// there's room. overflow-x-auto stays on the wrapper as a safety net
// for the very narrowest devices -- harmless when it isn't needed.
//
// Icons match the stroke-based SVG style used in Analytics.jsx (OI
// Analytics tab) instead of raw glyphs -- currentColor-driven, so they
// actually pick up each pill's tone color reliably across OS/fonts.

const IconCheck = ({ size = 11 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
);
const IconAlertTriangle = ({ size = 11 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
);
const IconTriangleUp = ({ size = 11 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="12 4 20 18 4 18"/></svg>
);
const IconTriangleDown = ({ size = 11 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="12 20 4 6 20 6"/></svg>
);

const GRADE_COLOR = {
  'A+': 'text-emerald-400', 'A': 'text-emerald-400', 'B': 'text-lime-400',
  'C': 'text-amber-400', 'D': 'text-rose-400',
}

// Aug 28 2026: Technical badge tone -- matches the RSI thresholds
// get_technical_signal() actually uses server-side (>=60 Bullish,
// <=40 Bearish, else Neutral), not a separate scale invented here.
const TECH_TONE = { Bullish: 'green', Neutral: 'gray', Bearish: 'red' }

function Pill({ children, tone }) {
  const tones = {
    green: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/25',
    red: 'bg-rose-500/15 text-rose-400 border border-rose-500/25',
    amber: 'bg-amber-500/15 text-amber-400 border border-amber-500/25',
    gray: 'bg-slate-700/30 text-slate-400 border border-slate-600/30',
  }
  return <span className={`inline-flex items-center gap-1 text-[11px] font-semibold px-1.5 sm:px-2 py-0.5 rounded-full whitespace-nowrap ${tones[tone]}`}>{children}</span>
}

export default function Watchlist() {
  const { signals, loading, error } = useSignals()
  // Aug 28 2026: 52-week High/Low + Technical (RSI-based Bullish/
  // Neutral/Bearish) -- fetched per-symbol from the new
  // /api/52-week-range/<symbol>/ endpoint (views.py), separate from
  // useSignals() since that data isn't part of the signal object at
  // all. Fetched in parallel, per-symbol failures isolated (tested in
  // test_watchlist_fetch_logic.js) so one bad symbol never blanks the
  // whole table -- missing/failed entries just render as an honest
  // dash, never a guess.
  const [rangeData, setRangeData] = useState({})

  useEffect(() => {
    if (!signals || signals.length === 0) return
    let mounted = true
    const fetchRanges = async () => {
      const results = {}
      await Promise.all(signals.map(async (s) => {
        try {
          const res = await fetch(`${API_BASE}/api/52-week-range/${s.symbol}/`)
          if (!res.ok) throw new Error('HTTP ' + res.status)
          results[s.symbol] = await res.json()
        } catch (err) {
          results[s.symbol] = null
        }
      }))
      if (mounted) setRangeData(results)
    }
    fetchRanges()
    // Same 30s cadence as the other market-summary-fed panels tonight.
    const interval = setInterval(fetchRanges, 30000)
    return () => { mounted = false; clearInterval(interval) }
  }, [(signals || []).map(s => s.symbol).join(',')])

  if (loading) {
    return <div className="p-10 text-center text-slate-500">Loading watchlist...</div>
  }
  if (error) {
    return <div className="p-10 text-center text-slate-500">Couldn't load watchlist: {error}</div>
  }
  if (signals.length === 0) {
    return <div className="p-10 text-center text-slate-500">No watchlist items</div>
  }

  const fmt = (n) => (n == null || isNaN(n)) ? '—' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800">
      <table className="w-full text-xs sm:text-sm">
        <thead>
          <tr className="bg-slate-900/60 text-slate-500 text-[11px] uppercase tracking-wide">
            <th className="text-left px-2.5 sm:px-4 py-2 sm:py-2.5 font-medium">Symbol</th>
            <th className="text-right px-2 sm:px-4 py-2 sm:py-2.5 font-medium">Price</th>
            <th className="text-right px-2 sm:px-4 py-2 sm:py-2.5 font-medium">Chg%</th>
            <th className="text-center px-1.5 sm:px-4 py-2 sm:py-2.5 font-medium">Grade</th>
            <th className="text-right px-2 sm:px-4 py-2 sm:py-2.5 font-medium">Entry</th>
            <th className="text-right px-2 sm:px-4 py-2 sm:py-2.5 font-medium">SL</th>
            <th className="text-center px-1.5 sm:px-4 py-2 sm:py-2.5 font-medium">
              <span className="sm:hidden">OI</span>
              <span className="hidden sm:inline">OI Status</span>
            </th>
            <th className="text-center px-1.5 sm:px-4 py-2 sm:py-2.5 font-medium">Signal</th>
            <th className="text-right px-2 sm:px-4 py-2 sm:py-2.5 font-medium whitespace-nowrap">
              <span className="sm:hidden">52W</span>
              <span className="hidden sm:inline">52W High / Low</span>
            </th>
            <th className="text-center px-1.5 sm:px-4 py-2 sm:py-2.5 font-medium">
              <span className="sm:hidden">Tech</span>
              <span className="hidden sm:inline">Technical</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {signals.map((s) => (
            <tr key={s.symbol} className="border-t border-slate-800/60 hover:bg-slate-900/40 transition-colors">
              <td className="px-2.5 sm:px-4 py-2.5 sm:py-3 font-semibold text-sky-400 whitespace-nowrap">{s.symbol}</td>
              <td className="px-2 sm:px-4 py-2.5 sm:py-3 text-right text-white whitespace-nowrap">₹{fmt(s.price)}</td>
              <td className={`px-2 sm:px-4 py-2.5 sm:py-3 text-right font-medium whitespace-nowrap ${(s.change_percent || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {(s.change_percent || 0) >= 0 ? '+' : ''}{s.change_percent}%
              </td>
              <td className={`px-1.5 sm:px-4 py-2.5 sm:py-3 text-center font-bold ${GRADE_COLOR[s.grade] || 'text-slate-400'}`}>{s.grade}</td>
              <td className="px-2 sm:px-4 py-2.5 sm:py-3 text-right text-white whitespace-nowrap">₹{fmt(s.entry)}</td>
              <td className="px-2 sm:px-4 py-2.5 sm:py-3 text-right text-rose-400 whitespace-nowrap">₹{fmt(s.sl)}</td>
              <td className="px-1.5 sm:px-4 py-2.5 sm:py-3 text-center">
                {s.oi_confirmation === 'CONFIRMED' && <Pill tone="green"><IconCheck /><span className="hidden sm:inline">Confirmed</span></Pill>}
                {s.oi_confirmation === 'CONFLICT' && <Pill tone="red"><IconAlertTriangle /><span className="hidden sm:inline">Conflict</span></Pill>}
                {(!s.oi_confirmation || s.oi_confirmation === 'NO_DATA' || s.oi_confirmation === 'NEUTRAL') && <Pill tone="gray">—</Pill>}
              </td>
              <td className="px-1.5 sm:px-4 py-2.5 sm:py-3 text-center">
                {s.action === 'BUY'
                  ? <Pill tone="green"><IconTriangleUp /><span className="hidden sm:inline">BUY</span></Pill>
                  : <Pill tone="red"><IconTriangleDown /><span className="hidden sm:inline">SELL</span></Pill>}
              </td>
              <td className="px-2 sm:px-4 py-2.5 sm:py-3 text-right whitespace-nowrap">
                {rangeData[s.symbol]?.high52w != null ? (
                  <>
                    <span className="text-emerald-400">₹{fmt(rangeData[s.symbol].high52w)}</span>
                    {' / '}
                    <span className="text-rose-400">₹{fmt(rangeData[s.symbol].low52w)}</span>
                  </>
                ) : (
                  <span className="text-slate-600">—</span>
                )}
              </td>
              <td className="px-1.5 sm:px-4 py-2.5 sm:py-3 text-center">
                {rangeData[s.symbol]?.technical?.label ? (
                  <Pill tone={TECH_TONE[rangeData[s.symbol].technical.label] || 'gray'}>
                    {rangeData[s.symbol].technical.label}
                  </Pill>
                ) : (
                  <Pill tone="gray">—</Pill>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
