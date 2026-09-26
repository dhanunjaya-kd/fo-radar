"""
backend/fundamentals_research/services/confluence.py

Sep 26 2026. Per spec: "Do not hide conflicting evidence inside one
combined score... Do not create arbitrary weights or claim the
combined score is predictive unless it has been validated through
appropriate historical testing." This has NOT been historically
validated, so there is deliberately no combined score anywhere in
this file -- only separate, independently-labeled assessments per
dimension, plus a plain-language note on what specific combination is
present (e.g. "strong fundamentals + bearish technicals") so the
conflict itself is visible, not resolved into one number.
"""
from typing import Dict, Any, Optional


def _label_fundamental_quality(latest_financial, bs, cf) -> Dict[str, str]:
    if latest_financial is None:
        return {'assessment': 'Insufficient data', 'reason': 'No financial statement on file.'}

    signals = []
    if latest_financial.revenue_growth_yoy_pct is not None:
        signals.append(('revenue growth', float(latest_financial.revenue_growth_yoy_pct) > 0))
    if latest_financial.pat_growth_yoy_pct is not None:
        signals.append(('PAT growth', float(latest_financial.pat_growth_yoy_pct) > 0))
    if cf is not None and cf.cfo_to_pat is not None:
        signals.append(('cash conversion', float(cf.cfo_to_pat) >= 0.8))
    if bs is not None and bs.debt_equity is not None:
        signals.append(('leverage', float(bs.debt_equity) < 1.0))

    if not signals:
        return {'assessment': 'Insufficient data', 'reason': 'No comparable financial signals available.'}

    positive_count = sum(1 for _, ok in signals if ok)
    reason = ', '.join(f"{name} {'positive' if ok else 'negative'}" for name, ok in signals)
    if positive_count == len(signals):
        return {'assessment': 'Strong', 'reason': reason}
    if positive_count == 0:
        return {'assessment': 'Weak', 'reason': reason}
    return {'assessment': 'Mixed', 'reason': reason}


def _label_valuation_context(val) -> Dict[str, str]:
    if val is None or val.pe is None:
        return {'assessment': 'Insufficient data', 'reason': 'No valuation data on file.'}
    pe = float(val.pe)
    if val.distance_from_52w_high_pct is not None:
        dist = float(val.distance_from_52w_high_pct)
        return {'assessment': 'Context provided, not a verdict', 'reason': f"P/E {pe}x, {abs(dist):.1f}% {'below' if dist < 0 else 'above'} 52-week high. No sector P/E benchmark available to judge cheap/expensive."}
    return {'assessment': 'Context provided, not a verdict', 'reason': f"P/E {pe}x. No sector P/E benchmark available to judge cheap/expensive."}


def _label_technical_trend(trend_classification: Optional[Dict[str, str]]) -> Dict[str, str]:
    if not trend_classification:
        return {'assessment': 'Insufficient data', 'reason': 'No technical data available.'}
    return {'assessment': trend_classification.get('classification', 'Insufficient data'), 'reason': trend_classification.get('reason', '')}


def _label_momentum(technicals: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not technicals or technicals.get('rsi') is None:
        return {'assessment': 'Insufficient data', 'reason': 'RSI unavailable.'}
    rsi = technicals['rsi']
    if rsi >= 70:
        return {'assessment': 'Overbought', 'reason': f'RSI {rsi}'}
    if rsi <= 30:
        return {'assessment': 'Oversold', 'reason': f'RSI {rsi}'}
    return {'assessment': 'Neutral', 'reason': f'RSI {rsi}'}


def _label_volume_confirmation(technicals: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not technicals or technicals.get('volume_avg') is None:
        return {'assessment': 'Insufficient data', 'reason': 'Volume data unavailable.'}
    # This module only has the 20-day average, not today's actual volume vs
    # that average (technical_analysis.py's snapshot doesn't currently expose
    # today's raw volume separately) -- stated honestly rather than guessed.
    return {'assessment': 'Data available, comparison not computed', 'reason': f"20-day average volume: {technicals['volume_avg']:,.0f}. Today's volume vs. average is not currently tracked by this module."}


def _label_data_quality(has_fundamentals: bool, has_technicals: bool) -> Dict[str, str]:
    if has_fundamentals and has_technicals:
        return {'assessment': 'Both fundamental and technical data available', 'reason': ''}
    if has_fundamentals:
        return {'assessment': 'Fundamental data only -- technical data unavailable', 'reason': ''}
    if has_technicals:
        return {'assessment': 'Technical data only -- fundamental data unavailable', 'reason': ''}
    return {'assessment': 'Insufficient data', 'reason': 'Neither fundamental nor technical data available.'}


def build_confluence(snapshot, technicals: Optional[Dict[str, Any]], trend_classification: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """
    Returns separate, independently-labeled assessments -- never a
    combined score. snapshot is a ResearchSnapshot; technicals/
    trend_classification come from technical_analysis.py (already
    computed elsewhere, passed in rather than re-fetched here).
    """
    latest_financial = snapshot.financials.order_by('-fiscal_year').first()
    bs = snapshot.balance_sheets.order_by('-fiscal_year').first()
    cf = snapshot.cash_flows.order_by('-fiscal_year').first()
    val = getattr(snapshot, 'valuation', None)

    fundamental_quality = _label_fundamental_quality(latest_financial, bs, cf)
    valuation_context = _label_valuation_context(val)
    technical_trend = _label_technical_trend(trend_classification)
    momentum = _label_momentum(technicals)
    volume_confirmation = _label_volume_confirmation(technicals)
    data_quality = _label_data_quality(latest_financial is not None, technicals is not None)

    # Plain-language note on the specific combination present -- the
    # spec's own examples ("strong fundamentals + bearish technicals"),
    # not a score. Only stated when both sides have real data --
    # otherwise it would be comparing a real assessment to "insufficient
    # data," which isn't a combination worth naming.
    combination_note = None
    if fundamental_quality['assessment'] in ('Strong', 'Weak', 'Mixed') and technical_trend['assessment'] not in ('Insufficient data',):
        combination_note = f"{fundamental_quality['assessment']} fundamentals + {technical_trend['assessment'].lower()}"

    return {
        'fundamental_quality': fundamental_quality,
        'financial_trend': {'assessment': 'See Financial Charts section for revenue/PAT/margin trend over time.', 'reason': ''},
        'valuation_context': valuation_context,
        'technical_trend': technical_trend,
        'momentum': momentum,
        'volume_confirmation': volume_confirmation,
        'sector_alignment': {'assessment': 'Not available', 'reason': 'No sector benchmark/index comparison currently wired.'},
        'data_quality': data_quality,
        'combination_note': combination_note,
        'note': 'These are separate, independent assessments -- not a combined score. No historical validation has been performed on any weighting, so none is offered.',
    }
