import React, { useState, useEffect } from 'react';
import api from '../services/api';

const IconBarChart = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/></svg>
);
const IconTrendingUp = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
);
const IconTrendingDown = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg>
);
const IconInfo = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
);
const IconChevronDown = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
);
const IconChevronUp = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="18 15 12 9 6 15"/></svg>
);
const IconActivity = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
);
const IconAlertTriangle = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
);

const Analytics = ({ stock, onStockSelect }) => {
  const [selectedExpiry, setSelectedExpiry] = useState('current');
  const [showGreeks, setShowGreeks] = useState(false);
  const [oiData, setOiData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // This used to hardcode 'RELIANCE' with no way to pick a different
  // stock -- App.jsx renders <Analytics /> with no props, so it was
  // permanently stuck on one symbol regardless of what's in your
  // watchlist. Now defaults to your top live signal (if any) and lets
  // you search/pick any other symbol.
  const [activeSymbol, setActiveSymbol] = useState(stock?.symbol || null);
  const [searchInput, setSearchInput] = useState('');
  const [watchlistSymbols, setWatchlistSymbols] = useState([]);

  useEffect(() => {
    if (stock?.symbol) return; // parent explicitly picked one, don't override
    api.getSignals?.().then((res) => {
      const list = Array.isArray(res) ? res : (res?.signals || []);
      const syms = list.map(s => s.symbol);
      setWatchlistSymbols(syms);
      if (!activeSymbol && syms.length > 0) setActiveSymbol(syms[0]);
      else if (!activeSymbol) setActiveSymbol('RELIANCE'); // last-resort default only if truly nothing else to show
    }).catch(() => {
      if (!activeSymbol) setActiveSymbol('RELIANCE');
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSearch = (e) => {
    e.preventDefault();
    const sym = searchInput.trim().toUpperCase();
    if (sym) setActiveSymbol(sym);
  };

  useEffect(() => {
    let cancelled = false;
    const symbol = activeSymbol;
    if (!symbol) return;

    setLoading(true);
    setError(null);

    api.getOptionAnalytics(symbol)
      .then((res) => {
        if (cancelled) return;

        if (!res.live) {
          // Honest failure state -- this used to silently fall back to
          // Math.random() data that looked identical to real numbers.
          // Now: no live option chain, no chart. Say so.
          setOiData(null);
          setError(res.error || 'No live option chain available for this symbol.');
          return;
        }

        setOiData({
          symbol: res.symbol,
          spot: res.spot,
          pcr: res.pcr != null ? res.pcr.toFixed(2) : '—',
          maxPain: res.maxPain,
          atmIv: res.atmIv != null ? res.atmIv.toFixed(1) : '—',
          atmStrike: res.atmStrike,
          support: res.support,
          resistance: res.resistance,
          oiBuildup: res.oiBuildup,
          atmGreeks: res.greeks || {},
          totalCeOi: res.totalCeOi || 0,
          totalPeOi: res.totalPeOi || 0,
          ceOiChg: res.ceOiChg || 0,
          peOiChg: res.peOiChg || 0,
          ceData: (res.ceData || []).map(d => ({
            strike: d.strike, ltp: d.ltp, oi: d.oi,
            oiChg: d.oi_chg_pct != null ? d.oi_chg_pct.toFixed(1) : '0.0',
            iv: d.iv != null ? d.iv.toFixed(1) : '—',
            volume: d.volume,
            delta: d.delta, gamma: d.gamma, theta: d.theta, vega: d.vega,
          })),
          peData: (res.peData || []).map(d => ({
            strike: d.strike, ltp: d.ltp, oi: d.oi,
            oiChg: d.oi_chg_pct != null ? d.oi_chg_pct.toFixed(1) : '0.0',
            iv: d.iv != null ? d.iv.toFixed(1) : '—',
            volume: d.volume,
            delta: d.delta, gamma: d.gamma, theta: d.theta, vega: d.vega,
          })),
        });
      })
      .catch((e) => {
        if (cancelled) return;
        setOiData(null);
        setError(e.message || 'Failed to load option chain.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [activeSymbol, selectedExpiry]);

  const searchBar = (
    <form onSubmit={handleSearch} className="flex items-center gap-2 mb-4 flex-wrap">
      <input
        type="text"
        value={searchInput}
        onChange={(e) => setSearchInput(e.target.value)}
        placeholder="Search any symbol e.g. TCS, INFY..."
        className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 flex-1 min-w-[180px]"
      />
      <button type="submit" className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors">
        Search
      </button>
      {watchlistSymbols.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          {watchlistSymbols.slice(0, 8).map(sym => (
            <button
              key={sym}
              onClick={() => setActiveSymbol(sym)}
              className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                sym === activeSymbol
                  ? 'bg-blue-500/20 border-blue-500 text-blue-300'
                  : 'bg-slate-800 border-slate-700 text-slate-400 hover:border-slate-500'
              }`}
            >
              {sym}
            </button>
          ))}
        </div>
      )}
    </form>
  );

  if (!activeSymbol || loading) {
    return (
      <div>
        {searchBar}
        <div className="bg-slate-900 rounded-lg border border-slate-800 p-8 text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400 mx-auto mb-4" />
          <p className="text-slate-400">Loading OI Analytics{activeSymbol ? ` for ${activeSymbol}` : ''}...</p>
        </div>
      </div>
    );
  }

  if (error || !oiData) {
    return (
      <div>
        {searchBar}
        <div className="bg-slate-900 rounded-lg border border-slate-800 p-8 text-center">
          <span className="text-amber-400 inline-block mb-3"><IconAlertTriangle /></span>
          <p className="text-slate-300 font-medium mb-1">No live option chain data for {activeSymbol}</p>
          <p className="text-slate-500 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  const { ceData, peData, pcr, maxPain, atmIv, atmStrike, spot } = oiData;

  return (
    <div className="space-y-6">
      {searchBar}
      <div className="bg-slate-900 rounded-lg border border-slate-800 p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <span className="text-blue-400"><IconBarChart /></span>
            <div>
              <h2 className="text-xl font-bold text-white">Options Analytics</h2>
              <p className="text-sm text-slate-500">
                {oiData.symbol} • Spot: ₹{spot.toFixed(2)}
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            {['current', 'next', 'monthly'].map(exp => (
              <button
                key={exp}
                onClick={() => setSelectedExpiry(exp)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium capitalize transition-colors ${
                  selectedExpiry === exp
                    ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                    : 'bg-slate-800 text-slate-400 border border-slate-700 hover:border-slate-600'
                }`}
              >
                {exp === 'current' ? 'Current Expiry' : exp === 'next' ? 'Next Expiry' : 'Monthly'}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <MetricCard label="Put-Call Ratio (OI)" value={pcr} description=">1 = Bearish bias, <1 = Bullish bias" color={parseFloat(pcr) > 1 ? 'rose' : 'emerald'} />
          <MetricCard label="Max Pain" value={`₹${maxPain}`} description="Strike where option buyers lose most" color="blue" />
          <MetricCard label="ATM Implied Vol" value={`${atmIv}%`} description="Expected price swing (annualized)" color="amber" />
          <MetricCard label="ATM Strike" value={`₹${atmStrike}`} description="Nearest strike to current spot price" color="purple" />
        </div>

        <div className="bg-slate-800/30 rounded-lg p-4 mb-6 border border-slate-700/50">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-blue-400"><IconInfo /></span>
            <h3 className="text-sm font-semibold text-white">Understanding Options</h3>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-emerald-400"><IconTrendingUp /></span>
                <span className="font-semibold text-emerald-400">CE = Call Option</span>
              </div>
              <p className="text-slate-400 text-xs leading-relaxed">
                <strong className="text-slate-300">Bet that price will GO UP.</strong> Buying CE gives you the 
                right to buy at the strike price. If {oiData.symbol} rises above strike + premium, you profit. 
                <span className="block mt-1 text-emerald-400/80">Example: {oiData.symbol} CE {atmStrike} means "I bet price will go above ₹{atmStrike}"</span>
              </p>
            </div>
            <div className="bg-rose-500/5 border border-rose-500/20 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-rose-400"><IconTrendingDown /></span>
                <span className="font-semibold text-rose-400">PE = Put Option</span>
              </div>
              <p className="text-slate-400 text-xs leading-relaxed">
                <strong className="text-slate-300">Bet that price will GO DOWN.</strong> Buying PE gives you the 
                right to sell at the strike price. If {oiData.symbol} falls below strike - premium, you profit.
                <span className="block mt-1 text-rose-400/80">Example: {oiData.symbol} PE {atmStrike} means "I bet price will fall below ₹{atmStrike}"</span>
              </p>
            </div>
          </div>
        </div>

        {/* Desktop / tablet: full CE | Strike | PE table, unchanged from before */}
        <div className="hidden sm:block overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-800 text-slate-400 text-xs uppercase tracking-wider">
                <th className="p-3 text-left rounded-tl-lg">
                  <div className="text-emerald-400 font-bold">CALL (CE)</div>
                  <div className="text-[10px] text-slate-500 font-normal">Bullish Bet ↑</div>
                </th>
                <th className="p-3 text-left">LTP</th>
                <th className="p-3 text-left">OI</th>
                <th className="p-3 text-left">OI Chg</th>
                <th className="p-3 text-center bg-slate-700/50">
                  <div className="text-white font-bold">Strike</div>
                  <div className="text-[10px] text-slate-500 font-normal">Exercise Price</div>
                </th>
                <th className="p-3 text-right">OI Chg</th>
                <th className="p-3 text-right">OI</th>
                <th className="p-3 text-right">LTP</th>
                <th className="p-3 text-right rounded-tr-lg">
                  <div className="text-rose-400 font-bold">PUT (PE)</div>
                  <div className="text-[10px] text-slate-500 font-normal">Bearish Bet ↓</div>
                </th>
              </tr>
            </thead>
            <tbody>
              {ceData.map((ce, idx) => {
                const pe = peData[idx];
                const isATM = ce.strike === atmStrike;
                const ceOiUp = parseFloat(ce.oiChg) > 0;
                const peOiUp = parseFloat(pe.oiChg) > 0;

                return (
                  <tr key={ce.strike} className={`border-t border-slate-700/50 ${isATM ? 'bg-blue-500/5' : ''}`}>
                    <td className="p-3">
                      <div className="flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full ${ceOiUp ? 'bg-emerald-400' : 'bg-rose-400'}`} />
                        <div>
                          <div className="text-emerald-400 font-medium">{oiData.symbol} CE {ce.strike}</div>
                          <div className="text-[10px] text-slate-600">IV: {ce.iv}% | Vol: {(ce.volume/1000).toFixed(0)}K</div>
                        </div>
                      </div>
                    </td>
                    <td className="p-3 text-emerald-400 font-bold">₹{ce.ltp}</td>
                    <td className="p-3 text-slate-300">{(ce.oi/100000).toFixed(1)}L</td>
                    <td className={`p-3 ${ceOiUp ? 'text-emerald-400' : 'text-rose-400'}`}>
                      <div className="flex items-center gap-1">
                        {ceOiUp ? <IconTrendingUp /> : <IconTrendingDown />}
                        {ce.oiChg}%
                      </div>
                    </td>
                    <td className={`p-3 text-center font-bold ${isATM ? 'text-blue-400 bg-blue-500/10' : 'text-slate-300'}`}>
                      ₹{ce.strike}
                      {isATM && <span className="ml-1 text-[10px] bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded">ATM</span>}
                    </td>
                    <td className={`p-3 text-right ${peOiUp ? 'text-emerald-400' : 'text-rose-400'}`}>
                      <div className="flex items-center justify-end gap-1">
                        {peOiUp ? <IconTrendingUp /> : <IconTrendingDown />}
                        {pe.oiChg}%
                      </div>
                    </td>
                    <td className="p-3 text-right text-slate-300">{(pe.oi/100000).toFixed(1)}L</td>
                    <td className="p-3 text-right text-rose-400 font-bold">₹{pe.ltp}</td>
                    <td className="p-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div>
                          <div className="text-rose-400 font-medium">{oiData.symbol} PE {pe.strike}</div>
                          <div className="text-[10px] text-slate-600">IV: {pe.iv}% | Vol: {(pe.volume/1000).toFixed(0)}K</div>
                        </div>
                        <div className={`w-2 h-2 rounded-full ${peOiUp ? 'bg-emerald-400' : 'bg-rose-400'}`} />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Mobile: stacked per-strike cards, CE/PE side by side. Same fields
            as the desktop table, just reflowed instead of squeezed into 9
            horizontal columns -- a real CE|Strike|PE comparison doesn't fit
            a phone width any other way without losing the point of it. */}
        <div className="sm:hidden space-y-2">
          {ceData.map((ce, idx) => {
            const pe = peData[idx];
            const isATM = ce.strike === atmStrike;
            const ceOiUp = parseFloat(ce.oiChg) > 0;
            const peOiUp = parseFloat(pe.oiChg) > 0;

            return (
              <div key={ce.strike} className={`rounded-lg border p-3 ${isATM ? 'border-blue-500/40 bg-blue-500/5' : 'border-slate-700/50 bg-slate-800/20'}`}>
                <div className="flex items-center justify-center gap-2 mb-2">
                  <span className="text-white font-bold text-sm">₹{ce.strike}</span>
                  {isATM && <span className="text-[10px] bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded">ATM</span>}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="bg-emerald-500/5 border border-emerald-500/20 rounded p-2">
                    <div className="text-[10px] text-emerald-400 font-semibold mb-1">CALL (CE)</div>
                    <div className="text-emerald-400 font-bold">₹{ce.ltp}</div>
                    <div className="text-[10px] text-slate-400 mt-1">OI {(ce.oi/100000).toFixed(1)}L</div>
                    <div className={`text-[10px] flex items-center gap-1 mt-0.5 ${ceOiUp ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {ceOiUp ? <IconTrendingUp /> : <IconTrendingDown />}{ce.oiChg}%
                    </div>
                    <div className="text-[10px] text-slate-600 mt-1">IV {ce.iv}% · Vol {(ce.volume/1000).toFixed(0)}K</div>
                  </div>
                  <div className="bg-rose-500/5 border border-rose-500/20 rounded p-2 text-right">
                    <div className="text-[10px] text-rose-400 font-semibold mb-1">PUT (PE)</div>
                    <div className="text-rose-400 font-bold">₹{pe.ltp}</div>
                    <div className="text-[10px] text-slate-400 mt-1">OI {(pe.oi/100000).toFixed(1)}L</div>
                    <div className={`text-[10px] flex items-center justify-end gap-1 mt-0.5 ${peOiUp ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {peOiUp ? <IconTrendingUp /> : <IconTrendingDown />}{pe.oiChg}%
                    </div>
                    <div className="text-[10px] text-slate-600 mt-1">IV {pe.iv}% · Vol {(pe.volume/1000).toFixed(0)}K</div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-4">
          <button
            onClick={() => setShowGreeks(!showGreeks)}
            className="flex items-center gap-2 text-sm text-blue-400 hover:text-blue-300 transition-colors"
          >
            {showGreeks ? <IconChevronUp /> : <IconChevronDown />}
            {showGreeks ? 'Hide Greeks' : 'Show Greeks (Delta, Gamma, Theta, Vega)'}
          </button>

          {showGreeks && (
            <div className="mt-3 bg-slate-800/30 rounded-lg p-4 border border-slate-700/50">
              <p className="text-xs text-slate-500 mb-3">ATM strike ₹{atmStrike} — CE (call) Greeks</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <GreekExplain label="Delta" value={oiData.atmGreeks?.CE?.delta ?? '—'} desc="Price change per ₹1 move in underlying" />
                <GreekExplain label="Gamma" value={oiData.atmGreeks?.CE?.gamma ?? '—'} desc="Rate of Delta change" />
                <GreekExplain label="Theta" value={oiData.atmGreeks?.CE?.theta ?? '—'} desc="Daily time decay (loss)" />
                <GreekExplain label="Vega" value={oiData.atmGreeks?.CE?.vega ?? '—'} desc="Price change per 1% IV move" />
              </div>
              <p className="text-xs text-slate-500 mb-3">ATM strike ₹{atmStrike} — PE (put) Greeks</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <GreekExplain label="Delta" value={oiData.atmGreeks?.PE?.delta ?? '—'} desc="Price change per ₹1 move in underlying" />
                <GreekExplain label="Gamma" value={oiData.atmGreeks?.PE?.gamma ?? '—'} desc="Rate of Delta change" />
                <GreekExplain label="Theta" value={oiData.atmGreeks?.PE?.theta ?? '—'} desc="Daily time decay (loss)" />
                <GreekExplain label="Vega" value={oiData.atmGreeks?.PE?.vega ?? '—'} desc="Price change per 1% IV move" />
              </div>
              <div className="text-xs text-slate-500 bg-slate-800/50 rounded p-3">
                <span className="inline-block mr-1 text-amber-400"><IconAlertTriangle /></span>
                <strong className="text-slate-400">Pro Tip:</strong> High Gamma near ATM means your Delta changes fast — 
                profits/losses accelerate. High Theta means you're losing money every day just from time passing.
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="bg-slate-900 rounded-lg border border-slate-800 p-6">
        <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
          <span className="text-purple-400"><IconActivity /></span>
          OI Buildup Analysis
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <BuildupCard title="CE OI Buildup" value={`${(oiData.totalCeOi/100000).toFixed(1)}L`} trend="up" interpretation="High CE OI at resistance = Strong wall. Breakout above this level is powerful." color="emerald" />
          <BuildupCard title="PE OI Buildup" value={`${(oiData.totalPeOi/100000).toFixed(1)}L`} trend="up" interpretation="High PE OI at support = Floor established. Bounce likely from this zone." color="rose" />
          <BuildupCard title="Net OI Change" value={parseFloat(pcr) > 1 ? 'PE Heavy' : 'CE Heavy'} trend={parseFloat(pcr) > 1 ? 'down' : 'up'} interpretation={parseFloat(pcr) > 1 ? 'Writers are selling more Puts = Bullish stance (support expected)' : 'Writers are selling more Calls = Bearish stance (resistance expected)'} color={parseFloat(pcr) > 1 ? 'emerald' : 'rose'} />
        </div>
      </div>
    </div>
  );
};

const MetricCard = ({ label, value, description, color }) => {
  const colors = {
    emerald: 'border-emerald-500/20 bg-emerald-500/5',
    rose: 'border-rose-500/20 bg-rose-500/5',
    blue: 'border-blue-500/20 bg-blue-500/5',
    amber: 'border-amber-500/20 bg-amber-500/5',
    purple: 'border-purple-500/20 bg-purple-500/5',
  };
  const textColors = {
    emerald: 'text-emerald-400',
    rose: 'text-rose-400',
    blue: 'text-blue-400',
    amber: 'text-amber-400',
    purple: 'text-purple-400',
  };

  return (
    <div className={`border rounded-lg p-4 ${colors[color]}`}>
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold ${textColors[color]} mb-1`}>{value}</div>
      <div className="text-[10px] text-slate-600 leading-tight">{description}</div>
    </div>
  );
};

const GreekExplain = ({ label, value, desc }) => (
  <div className="bg-slate-800/50 rounded-lg p-3">
    <div className="text-xs text-slate-500 mb-1">{label}</div>
    <div className="text-lg font-bold text-white mb-1">{value}</div>
    <div className="text-[10px] text-slate-600">{desc}</div>
  </div>
);

const BuildupCard = ({ title, value, trend, interpretation, color }) => {
  const isUp = trend === 'up';
  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-slate-400">{title}</span>
        {isUp ? <span className="text-emerald-400"><IconTrendingUp /></span> : <span className="text-rose-400"><IconTrendingDown /></span>}
      </div>
      <div className={`text-xl font-bold ${color === 'emerald' ? 'text-emerald-400' : color === 'rose' ? 'text-rose-400' : 'text-blue-400'} mb-2`}>
        {value}
      </div>
      <p className="text-xs text-slate-500 leading-relaxed">{interpretation}</p>
    </div>
  );
};

export default Analytics;
