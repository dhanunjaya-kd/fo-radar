"""
screener/options_analytics.py

Pure, dependency-light functions that turn a RAW Fyers option-chain response
into the numbers a trader actually wants: PCR, Max Pain, CE/PE OI buildup,
support/resistance (from OI walls), and IV (Black-Scholes, computed locally
because Fyers' option-chain endpoint does not return IV/Greeks at all).
"""
import math


def parse_option_chain(raw_response):
    data = (raw_response or {}).get('data', {}) or {}
    chain = data.get('optionsChain', []) or []
    spot = 0.0
    by_strike = {}
    for row in chain:
        opt_type = (row.get('option_type') or '').upper()
        if opt_type not in ('CE', 'PE'):
            spot = float(row.get('ltp') or row.get('fp') or spot or 0)
            continue
        strike = int(row.get('strike_price') or 0)
        entry = {
            'ltp': float(row.get('ltp') or 0),
            'oi': int(row.get('oi') or 0),
            'oi_chg': int(row.get('oich') or 0),
            'oi_chg_pct': float(row.get('oichp') or 0),
            'volume': int(row.get('volume') or 0),
            'bid': float(row.get('bid') or 0),
            'ask': float(row.get('ask') or 0),
            'symbol': row.get('symbol', ''),
        }
        slot = by_strike.setdefault(strike, {'strike': strike, 'ce': None, 'pe': None})
        slot['ce' if opt_type == 'CE' else 'pe'] = entry
    rows = sorted(by_strike.values(), key=lambda r: r['strike'])
    return {
        'spot': spot,
        'rows': rows,
        'call_oi_total_reported': data.get('callOi'),
        'put_oi_total_reported': data.get('putOi'),
        'expiry_data': data.get('expiryData', []),
    }


def compute_pcr(rows):
    ce_oi = sum((r['ce']['oi'] if r['ce'] else 0) for r in rows)
    pe_oi = sum((r['pe']['oi'] if r['pe'] else 0) for r in rows)
    if ce_oi <= 0:
        return None, ce_oi, pe_oi
    return round(pe_oi / ce_oi, 3), ce_oi, pe_oi


def compute_pcr_volume(rows):
    ce_vol = sum((r['ce']['volume'] if r['ce'] else 0) for r in rows)
    pe_vol = sum((r['pe']['volume'] if r['pe'] else 0) for r in rows)
    if ce_vol <= 0:
        return None, ce_vol, pe_vol
    return round(pe_vol / ce_vol, 3), ce_vol, pe_vol


def compute_oi_change(rows):
    ce_chg = sum((r['ce']['oi_chg'] if r['ce'] else 0) for r in rows)
    pe_chg = sum((r['pe']['oi_chg'] if r['pe'] else 0) for r in rows)
    return ce_chg, pe_chg


def classify_side_buildup(price_chg_pct, oi_chg):
    if price_chg_pct is None or oi_chg is None:
        return 'Unclear'
    if price_chg_pct >= 0 and oi_chg > 0:
        return 'Long Buildup'
    if price_chg_pct >= 0 and oi_chg <= 0:
        return 'Short Covering'
    if price_chg_pct < 0 and oi_chg > 0:
        return 'Short Buildup'
    return 'Long Unwinding'


def compute_max_pain(rows):
    strikes = [r['strike'] for r in rows]
    if not strikes:
        return None
    best_strike, best_loss = None, None
    for candidate in strikes:
        total_loss = 0
        for r in rows:
            k = r['strike']
            ce_oi = r['ce']['oi'] if r['ce'] else 0
            pe_oi = r['pe']['oi'] if r['pe'] else 0
            if candidate > k:
                total_loss += ce_oi * (candidate - k)
            if candidate < k:
                total_loss += pe_oi * (k - candidate)
        if best_loss is None or total_loss < best_loss:
            best_loss, best_strike = total_loss, candidate
    return best_strike


def compute_support_resistance(rows):
    ce_rows = [r for r in rows if r['ce']]
    pe_rows = [r for r in rows if r['pe']]
    resistance = max(ce_rows, key=lambda r: r['ce']['oi'])['strike'] if ce_rows else None
    support = max(pe_rows, key=lambda r: r['pe']['oi'])['strike'] if pe_rows else None
    return support, resistance


def compute_atm_straddle_price(rows, atm_strike):
    if atm_strike is None:
        return None
    atm_row = next((r for r in rows if r['strike'] == atm_strike), None)
    if not atm_row:
        return None
    ce_ltp = atm_row['ce']['ltp'] if atm_row['ce'] else None
    pe_ltp = atm_row['pe']['ltp'] if atm_row['pe'] else None
    if not ce_ltp or not pe_ltp or ce_ltp <= 0 or pe_ltp <= 0:
        return None
    return round(ce_ltp + pe_ltp, 2)


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _bs_price(S, K, T, r, sigma, option_type):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, (S - K) if option_type == 'CE' else (K - S))
    d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == 'CE':
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def implied_volatility(ltp, spot, strike, days_to_expiry, option_type, risk_free_rate=0.07):
    if ltp <= 0 or spot <= 0 or strike <= 0 or days_to_expiry <= 0:
        return None
    T = days_to_expiry / 365.0
    intrinsic = max(0.0, (spot - strike) if option_type == 'CE' else (strike - spot))
    if ltp < intrinsic:
        return None
    lo, hi = 0.001, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2
        price = _bs_price(spot, strike, T, risk_free_rate, mid, option_type)
        if price > ltp:
            hi = mid
        else:
            lo = mid
    return round(((lo + hi) / 2) * 100, 1)


def _greeks(S, K, T, r, sigma, option_type):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None
    d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    pdf_d1 = math.exp(-d1 ** 2 / 2) / math.sqrt(2 * math.pi)
    gamma = pdf_d1 / (S * sigma * math.sqrt(T))
    vega = S * pdf_d1 * math.sqrt(T) / 100
    if option_type == 'CE':
        delta = _norm_cdf(d1)
        theta = (-S * pdf_d1 * sigma / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * _norm_cdf(d2)) / 365
    else:
        delta = _norm_cdf(d1) - 1
        theta = (-S * pdf_d1 * sigma / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * _norm_cdf(-d2)) / 365
    return {'delta': round(delta, 3), 'gamma': round(gamma, 4), 'theta': round(theta, 2), 'vega': round(vega, 3)}


def compute_atm_iv(rows, spot, days_to_expiry):
    if not rows or spot <= 0:
        return None, None, {}
    atm_row = min(rows, key=lambda r: abs(r['strike'] - spot))
    atm_strike = atm_row['strike']
    T = days_to_expiry / 365.0
    ivs = []
    greeks = {}
    if atm_row['ce'] and atm_row['ce']['ltp'] > 0:
        iv_ce = implied_volatility(atm_row['ce']['ltp'], spot, atm_strike, days_to_expiry, 'CE')
        if iv_ce:
            ivs.append(iv_ce)
            greeks['CE'] = _greeks(spot, atm_strike, T, 0.07, iv_ce / 100, 'CE')
    if atm_row['pe'] and atm_row['pe']['ltp'] > 0:
        iv_pe = implied_volatility(atm_row['pe']['ltp'], spot, atm_strike, days_to_expiry, 'PE')
        if iv_pe:
            ivs.append(iv_pe)
            greeks['PE'] = _greeks(spot, atm_strike, T, 0.07, iv_pe / 100, 'PE')
    return (round(sum(ivs) / len(ivs), 1) if ivs else None), atm_strike, greeks


def enrich_rows_with_iv_greeks(rows, spot, days_to_expiry, risk_free_rate=0.07):
    T = days_to_expiry / 365.0
    for r in rows:
        for side in ('ce', 'pe'):
            leg = r.get(side)
            if not leg:
                continue
            opt_type = 'CE' if side == 'ce' else 'PE'
            iv = implied_volatility(leg['ltp'], spot, r['strike'], days_to_expiry, opt_type, risk_free_rate) if leg['ltp'] > 0 else None
            leg['iv'] = iv
            g = _greeks(spot, r['strike'], T, risk_free_rate, iv / 100, opt_type) if iv else None
            leg.update(g or {'delta': None, 'gamma': None, 'theta': None, 'vega': None})
    return rows


def estimate_option_premium(spot, strike, days_to_expiry, iv_pct, option_type, risk_free_rate=0.07):
    if spot <= 0 or strike <= 0 or days_to_expiry <= 0 or not iv_pct or iv_pct <= 0:
        return None
    T = days_to_expiry / 365.0
    sigma = iv_pct / 100
    price = _bs_price(spot, strike, T, risk_free_rate, sigma, option_type)
    g = _greeks(spot, strike, T, risk_free_rate, sigma, option_type)
    return {'price': round(max(price, 0.05), 2), 'delta': g['delta'] if g else None}


def analyze_option_chain(raw_response, days_to_expiry):
    parsed = parse_option_chain(raw_response)
    rows, spot = parsed['rows'], parsed['spot']
    if not rows or spot <= 0:
        return None
    enrich_rows_with_iv_greeks(rows, spot, days_to_expiry)
    pcr, ce_oi_total, pe_oi_total = compute_pcr(rows)
    pcr_volume, ce_vol_total, pe_vol_total = compute_pcr_volume(rows)
    ce_oi_chg, pe_oi_chg = compute_oi_change(rows)
    max_pain = compute_max_pain(rows)
    support, resistance = compute_support_resistance(rows)
    iv, atm_strike, greeks = compute_atm_iv(rows, spot, days_to_expiry)
    atm_straddle_price = compute_atm_straddle_price(rows, atm_strike)
    if ce_oi_chg > pe_oi_chg * 1.2:
        buildup = 'CE writing dominant (bearish)'
    elif pe_oi_chg > ce_oi_chg * 1.2:
        buildup = 'PE writing dominant (bullish)'
    else:
        buildup = 'Mixed / no clear dominance'
    return {
        'spot': spot,
        'pcr': pcr,
        'pcr_volume': pcr_volume,
        'ce_oi': ce_oi_total,
        'pe_oi': pe_oi_total,
        'ce_oi_total': ce_oi_total,
        'pe_oi_total': pe_oi_total,
        'ce_oi_chg': ce_oi_chg,
        'pe_oi_chg': pe_oi_chg,
        'max_pain': max_pain,
        'max_pain_dist_pct': round((spot - max_pain) / max_pain * 100, 2) if max_pain else None,
        'support': support,
        'resistance': resistance,
        'atm_strike': atm_strike,
        'atm_straddle_price': atm_straddle_price,
        'iv': iv,
        'oi_buildup': buildup,
        'greeks': greeks,
        'rows': rows,
    }
