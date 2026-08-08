import React, { useState, useEffect } from 'react'

export default function Header() {
  const [time, setTime] = useState(new Date().toLocaleTimeString('en-IN', { hour12: false }))

  useEffect(() => {
    const i = setInterval(() => setTime(new Date().toLocaleTimeString('en-IN', { hour12: false })), 1000)
    return () => clearInterval(i)
  }, [])

  return (
    <header className="flex items-center justify-between px-5 py-3.5 border-b border-sniper-border">
      <div className="flex items-center gap-3.5">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-green-900/60 to-green-950/40 border border-green-800/50 flex items-center justify-center">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#4ade80" strokeWidth="2" strokeLinecap="round">
            <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
          </svg>
        </div>
        <div>
          <h1 className="text-[17px] font-semibold tracking-wide text-sniper-text">F&O SNIPER SCANNER</h1>
          <p className="text-[11px] text-sniper-muted mt-0.5">NSE F&O • <span className="text-green-400">{time}</span> • LIVE</p>
        </div>
      </div>
      <div className="flex items-center gap-2.5">
        <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse-dot"/>
        <span className="text-[11px] text-sniper-muted">Market Open</span>
      </div>
    </header>
  )
}
