import React from 'react';
import './OptionsSignalCard.css';

const OptionsSignalCard = ({ data }) => {
  const d = data || {};
  return (
    <div className="os-card">
      {/* Top */}
      <div className="os-top">
        <div>
          <span className="os-name">{d.symbol}</span>
          <span className="os-price"> ₹{d.ltp}</span>
          <span className={d.change >= 0 ? 'green' : 'red'}>
            {' '}{d.change >= 0 ? '▲' : '▼'} {d.changePct}%
          </span>
        </div>
        <div className="os-grade">
          <div className="g-num">{d.grade}</div>
          <div className="g-label">{d.gradeLabel}</div>
          <div className="g-sub">GRADE</div>
        </div>
      </div>

      {/* Tags */}
      <div className="os-tags">
        <span className="tag-red">{d.confidence}% confidence</span>
        <span className="tag-gray">{d.sector}</span>
      </div>

      {/* Signal */}
      <div className="os-badge">📊 {d.signalLabel}</div>

      {/* 6-box grid */}
      <div className="os-grid">
        <div className="box"><div className="lbl">CE OI CHG</div><div className="val red">↑ {d.ceOiChg}</div><div className="sub red">CE WRITING</div><div className="sub red">(bearish)</div></div>
        <div className="box"><div className="lbl">PE OI CHG</div><div className="val green">↑ {d.peOiChg}</div><div className="sub green">PE WRITING</div><div className="sub green">(bullish)</div></div>
        <div className="box"><div className="lbl">PCR CHG</div><div className="val orange">↑ {d.pcrChg}%</div><div className="sub orange">PCR rising but still</div><div className="sub orange">bearish ({d.pcr})</div></div>
        <div className="box"><div className="lbl">MAX PAIN</div><div className="val red">₹{d.maxPain}</div><div className="note">MP dist {d.maxPainDist}%</div></div>
        <div className="box"><div className="lbl">PCR</div><div className="val blue">{d.pcr}</div><div className="note">calls dominant</div></div>
        <div className="box"><div className="lbl">IV</div><div className="val red">{d.iv}%</div><div className="note">HIGH vol</div></div>
      </div>

      {/* Levels */}
      <div className="os-levels">
        <span className="pill-red">📌 Resistance ₹{d.resistance}</span>
        <span className="pill-green">🛡 Support ₹{d.support}</span>
      </div>

      {/* Insights */}
      <div className="os-chips">
        {(d.insights || []).map((t, i) => <div key={i} className="chip">{t}</div>)}
      </div>

      {/* Trade Box */}
      <div className="os-trade">
        <div className="tsignal">▼ {d.tradeSignal}</div>
        <div className="trow">
          <div><div className="tlbl">Entry</div><div className="tval">₹{d.entry}</div></div>
          <div><div className="tlbl">Stop Loss</div><div className="tval red">₹{d.stopLoss}</div></div>
          <div><div className="tlbl">Target</div><div className="tval green">₹{d.target}</div></div>
        </div>
        <div className="tfoot">
          <span>⚠ {d.warning}</span>
          <span className="rr">R:R {d.rrRatio}</span>
        </div>
      </div>
    </div>
  );
};

export default OptionsSignalCard;