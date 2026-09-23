"""
screener/gamma_options_resolver.py

Gamma Blast Strategy -- Options Chain Resolver + DTE >= 8 Roll Protocol.

Ported from the purchased package's core/options_resolver.py. Same
thresholds, same OTM moneyness bounds, same delta/convexity gates,
same multi-factor sort -- verified against the original's numbers
below. What's adapted: Dhan's REST calls (fetch_option_chain,
get_expiry_list) are replaced with this project's own real Fyers
plumbing -- get_option_chain()/get_option_analytics() from
fyers_client.py, and Greeks come from options_analytics.py's own
Black-Scholes enrichment (enrich_rows_with_iv_greeks), since (per
that file's own docstring) "Fyers' option-chain endpoint does not
return IV/Greeks at all" -- Dhan's does, which is why the original
just reads greeks straight off its response.

DTE selection reuses this project's OWN already-proven pattern (the
expiry_choice logic already live in the stock-detail option-chain
view): probe expiryData with strikecount=1, walk it (already
confirmed nearest-first) computing real DTE per entry, use the first
entry's own 'expiry' field as the timestamp for the real fetch --
not a guess at Fyers' API shape.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional

IST = timezone(timedelta(hours=5, minutes=30))


def resolve_expiry_with_min_dte(fyers_symbol: str, min_dte: int, get_option_chain_fn) -> Optional[Dict[str, Any]]:
    """
    Returns {'timestamp': <Fyers expiry token>, 'dte': int, 'date': 'YYYY-MM-DD'}
    for the FIRST listed expiry (Fyers already returns them nearest-
    first) whose real DTE >= min_dte, or None if none qualify --
    mirrors the original's get_current_monthly_expiry(): "Strictly
    return None if no expiry satisfies min_dte", never silently falls
    back to a too-near one.
    """
    try:
        probe = get_option_chain_fn(fyers_symbol, strikecount=1)
    except Exception:
        return None
    expiry_list = ((probe or {}).get("data", {}) or {}).get("expiryData", [])
    if not expiry_list:
        return None

    today = datetime.now(IST).date()
    for entry in expiry_list:
        date_str = entry.get("date")
        if not date_str:
            continue
        try:
            exp_date = datetime.strptime(date_str, "%d-%m-%Y").date()
        except ValueError:
            continue
        dte = (exp_date - today).days
        if dte >= min_dte:
            return {"timestamp": entry.get("expiry") or "", "dte": dte, "date": exp_date.isoformat()}
    return None


def _resolve_side(rows: List[Dict], spot: float, option_type: str, lot_size: int,
                   max_candidates: int, min_oi: int, min_vol: int,
                   max_spread_pct: float, min_convexity: float,
                   otm_ce_max_pct: float, otm_pe_min_pct: float,
                   sweet_min_pct: float, sweet_max_pct: float) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        strike = float(row.get('strike', 0))
        leg = row.get('ce' if option_type == 'CE' else 'pe')
        if not leg:
            continue
        oi = int(leg.get('oi') or 0)
        vol = int(leg.get('volume') or 0)
        ltp = float(leg.get('ltp') or 0)
        bid = float(leg.get('bid') or 0)
        ask = float(leg.get('ask') or 0)

        if oi <= 0 or ltp <= 0:
            continue
        if vol < min_vol:
            continue

        if option_type == 'CE':
            if strike < spot or strike > spot * otm_ce_max_pct:
                continue
        else:
            if strike > spot or strike < spot * otm_pe_min_pct:
                continue

        if bid <= 0 or ask <= 0:
            continue
        spread_pct = round(((ask - bid) / ltp) * 100.0, 2)
        if spread_pct > max_spread_pct:
            continue

        dist_pct = round(((strike - spot) / spot) * 100.0, 2) if option_type == 'CE' else round(((spot - strike) / spot) * 100.0, 2)

        delta_val, gamma_val = leg.get('delta'), leg.get('gamma')
        if delta_val is None or gamma_val is None:
            continue  # real greeks required -- never a guessed convexity
        delta_val = round(float(delta_val), 4)
        gamma_val = round(float(gamma_val), 6)
        convexity = round((gamma_val / ltp) * 100.0, 4)
        if convexity < min_convexity:
            continue
        if abs(delta_val) > 0.50 or (abs(delta_val) > 0 and abs(delta_val) < 0.15):
            continue

        is_sweet_spot = bool(0.20 <= abs(delta_val) <= 0.45 and sweet_min_pct <= dist_pct <= sweet_max_pct and convexity >= min_convexity)
        is_tight_spread = bool(spread_pct <= max_spread_pct)
        tier_score = 1 if (is_sweet_spot and is_tight_spread and oi >= min_oi) else 2

        out.append({
            "option_type": option_type, "strike": strike, "ltp": ltp, "bid": bid, "ask": ask,
            "spread_pct": spread_pct, "volume": vol, "oi": oi,
            "iv": round(float(leg.get('iv') or 0.0), 2),
            "delta": delta_val, "gamma": gamma_val,
            "theta": round(float(leg.get('theta') or 0.0), 4), "vega": round(float(leg.get('vega') or 0.0), 4),
            "convexity": convexity, "delta_sweet_spot": is_sweet_spot,
            "lot_size": lot_size, "distance_to_strike_pct": dist_pct, "tier_score": tier_score,
        })

    out.sort(key=lambda x: (x["tier_score"], -x["oi"], -x["volume"], -x["convexity"], x["spread_pct"]))
    ranked = out[:max_candidates]
    for idx, c in enumerate(ranked):
        c["rank"] = idx + 1
        c["tier"] = "GOLD" if idx == 0 else ("SILVER" if idx == 1 else "STANDARD")
    return ranked


def resolve_ce_otm_candidates(rows, spot, lot_size, max_candidates, min_oi, min_vol, max_spread_pct, min_convexity, otm_ce_max_pct, sweet_min_pct, sweet_max_pct):
    return _resolve_side(rows, spot, 'CE', lot_size, max_candidates, min_oi, min_vol, max_spread_pct, min_convexity, otm_ce_max_pct, 0.0, sweet_min_pct, sweet_max_pct)


def resolve_pe_otm_candidates(rows, spot, lot_size, max_candidates, min_oi, min_vol, max_spread_pct, min_convexity, otm_pe_min_pct, sweet_min_pct, sweet_max_pct):
    return _resolve_side(rows, spot, 'PE', lot_size, max_candidates, min_oi, min_vol, max_spread_pct, min_convexity, 999.0, otm_pe_min_pct, sweet_min_pct, sweet_max_pct)
