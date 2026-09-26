"""
backend/fundamentals_research/services/entry_setup.py

Sep 26 2026. Per spec: "Every proposed level must be derived from
actual market data and a documented calculation method... If the
stock has no valid setup, display 'No validated entry setup currently
available.'" No LLM call in this module at all -- entry zones,
stops, and targets are pure arithmetic on real indicator values
already computed by technical_analysis.py (which itself reuses
screener/views.py's proven indicator engine, not reimplemented here).

DOCUMENTED METHOD (stated once, here, not hidden in code):
A validated LONG setup exists only when ALL of these hold on the
already-computed technicals:
  1. Confirmed uptrend: price > EMA20 > EMA50, ADX >= 20, +DI > -DI
     (the same ADX+DI convention classify_trend() already uses)
  2. Price is within 1x ATR of EMA20 -- a genuine pullback-to-support
     condition, not an arbitrary "close enough"
  3. RSI is between 35 and 65 -- excludes both an oversold reversal
     guess (spec: don't declare a bottom just because price is low)
     and an already-overbought entry

If ANY condition fails, the function returns the spec's own required
string, not a partial/best-effort setup.

Levels, when a setup IS validated:
  entry_zone = EMA20 +/- 0.5*ATR
  stop_loss  = EMA20 - 1.5*ATR (never above the recent 20-day support,
               whichever is the tighter/safer of the two)
  target_1   = entry + 1.5x the entry-to-stop risk (R-multiple)
  target_2   = entry + 3.0x the entry-to-stop risk
This R-multiple convention (not the exact numbers) mirrors the same
risk-management shape already used elsewhere in this project's Gamma
module (target_1_r_multiple/target_2_r_multiple) -- a consistent,
already-reviewed way to express targets as multiples of risk, not
independently invented here.
"""
from typing import Optional, Dict, Any


def _round(x):
    return round(x, 2) if x is not None else None


def build_entry_setup(technicals: Dict[str, Any]) -> Dict[str, Any]:
    """
    technicals: the dict returned by technical_analysis.get_technical_snapshot().
    Returns a dict with either a validated setup or the spec's exact
    "no setup" message -- never a partial/guessed setup.
    """
    if not technicals:
        return {'status': 'unavailable', 'message': 'No technical data available for this symbol.'}

    price = technicals.get('current_price')
    ema20, ema50 = technicals.get('ema20'), technicals.get('ema50')
    atr = technicals.get('atr')
    adx = technicals.get('adx')
    plus_di, minus_di = technicals.get('plus_di'), technicals.get('minus_di')
    rsi = technicals.get('rsi')
    support = technicals.get('support')

    required = [price, ema20, ema50, atr, adx, plus_di, minus_di, rsi]
    if any(v is None for v in required):
        return {'status': 'unavailable', 'message': 'No validated entry setup currently available -- required indicators missing.'}

    uptrend_confirmed = price > ema20 > ema50 and adx >= 20 and plus_di > minus_di
    near_ema20_pullback = atr > 0 and abs(price - ema20) <= atr
    rsi_constructive = 35 <= rsi <= 65

    conditions = {
        'confirmed_uptrend': uptrend_confirmed,
        'pullback_to_ema20': near_ema20_pullback,
        'rsi_constructive_not_extended': rsi_constructive,
    }

    if not all(conditions.values()):
        failed = [k for k, v in conditions.items() if not v]
        return {
            'status': 'no_setup',
            'message': 'No validated entry setup currently available.',
            'conditions_checked': conditions,
            'reason': f"Failed: {', '.join(failed)}.",
        }

    entry_low = ema20 - 0.5 * atr
    entry_high = ema20 + 0.5 * atr
    entry_mid = ema20

    # "Tighter/safer" stop = closer to entry = less capital at risk =
    # the HIGHER of the two candidate stop prices for a long position.
    # Typically support (20-day low) sits below the ATR-based stop, so
    # the ATR-based stop is used unless support is actually the closer
    # (higher, tighter) of the two.
    stop_from_atr = ema20 - 1.5 * atr
    stop_loss = max(stop_from_atr, support) if support is not None and support < entry_mid else stop_from_atr

    risk_per_share = entry_mid - stop_loss
    if risk_per_share <= 0:
        return {'status': 'no_setup', 'message': 'No validated entry setup currently available -- computed risk is non-positive.', 'conditions_checked': conditions}

    target_1 = entry_mid + 1.5 * risk_per_share
    target_2 = entry_mid + 3.0 * risk_per_share

    return {
        'status': 'setup_confirmed',
        'message': 'Setup confirmed under defined conditions.',
        'conditions_checked': conditions,
        'current_price': _round(price),
        'entry_zone': {'low': _round(entry_low), 'high': _round(entry_high)},
        'stop_loss': _round(stop_loss),
        'target_1': _round(target_1),
        'target_2': _round(target_2),
        'risk_per_share': _round(risk_per_share),
        'reward_to_risk_target_1': _round((target_1 - entry_mid) / risk_per_share),
        'reward_to_risk_target_2': _round((target_2 - entry_mid) / risk_per_share),
        'invalidation_condition': f"Price closes below stop loss ({_round(stop_loss)}), or price closes back below EMA50 ({_round(ema50)}).",
        'method': 'Pullback-to-EMA20 in a confirmed uptrend (price>EMA20>EMA50, ADX>=20 with +DI>-DI), entry zone +/-0.5x ATR around EMA20, stop 1.5x ATR below EMA20 (or recent support if tighter), targets at 1.5R/3R.',
    }
