"""
backend/fundamentals/ranking.py

Turns fundamentals_data.json into a ranked watchlist: stocks trading
well below their 52-week high, with strong-looking fundamentals.

There's no single "correct" way to combine P/E, ROE, Debt/Equity, and
growth into one score -- reasonable people weight these differently.
This uses PERCENTILE RANKING across each metric (not raw magnitude),
then averages the ranks -- transparent and comparable across very
different kinds of companies, rather than one opaque number with
hidden weights. Every input that went into a stock's rank is shown
alongside it, not hidden behind a single figure.

Only includes stocks with BOTH fundamentals and price data present --
a stock missing either half is left out rather than guessed at.
"""
import json
import os

# Anchored to backend/ (one level up from fundamentals/, via __file__)
# rather than a plain relative path -- same fix already needed for
# screener_client.py's session file. runner.py always runs from
# backend/ so a relative path works fine there, but this module will
# also get called from a Django view with a different working
# directory, where a relative path would silently look in the wrong
# place instead of erroring.
DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fundamentals_data.json")


def _percentile_rank(values, value, lower_is_better=False):
    """Returns value's percentile rank (0-100, higher = better) among
    values. Pass lower_is_better=True for metrics like P/E or
    Debt/Equity where a SMALLER number is actually the better one."""
    valid = [v for v in values if v is not None]
    if not valid or value is None:
        return None
    below = sum(1 for v in valid if v < value)
    pct = below / len(valid) * 100
    return round(100 - pct, 1) if lower_is_better else round(pct, 1)


def build_watchlist(data_file=DATA_FILE, min_discount_pct=-10, top_n=50):
    """
    Returns a ranked list of stocks at least min_discount_pct below
    their 52-week high (default: at least 10% below -- pct_off_52w_high
    is negative, so -10 means "10% or more below"), sorted best-first
    by a combined fundamentals rank.
    """
    if not os.path.exists(data_file):
        return []
    with open(data_file, "r", encoding="utf-8") as f:
        raw = json.load(f)

    candidates = []
    for symbol, entry in raw.items():
        f_data = entry.get("fundamentals")
        p_data = entry.get("price_levels")
        if not f_data or not p_data:
            continue
        pct_off_high = p_data.get("pct_off_52w_high")
        if pct_off_high is None or pct_off_high > min_discount_pct:
            continue  # not far enough below its 52-week high to qualify

        # A negative Debt/Equity is only possible when total equity
        # itself is negative (accumulated losses exceeding paid-in
        # capital) -- real financial distress, not a value opportunity.
        # Excluded entirely here, not just de-ranked: with negative
        # equity, ROE flips to a misleadingly POSITIVE number (negative
        # profit / negative equity), and Debt/Equity becomes
        # nonsensical. Caught live in the real full-universe ranking:
        # de-ranking just those two metrics still let a company with
        # almost no other usable data rank #1 on a single extreme,
        # thin Sales CAGR outlier (885%, almost certainly a low-base-
        # year artifact) -- a company failing this basic solvency
        # check doesn't belong on this list at all, regardless of how
        # any one remaining number looks.
        de = f_data.get("debt_to_equity")
        if de is not None and de < 0:
            continue

        candidates.append({
            "symbol": symbol,
            "company_name": f_data.get("company_name"),
            "pe_ratio": f_data.get("pe_ratio"),
            "roe_pct": f_data.get("roe_pct"),
            "debt_to_equity": f_data.get("debt_to_equity"),
            "sales_cagr_pct": f_data.get("sales_cagr_pct"),
            "pct_off_52w_high": pct_off_high,
            "current_price": p_data.get("latest_close"),
            "week52_low": p_data.get("week52_low"),
            "week52_high": p_data.get("week52_high"),
        })

    if not candidates:
        return []

    pe_values = [c["pe_ratio"] for c in candidates if c["pe_ratio"] is not None and c["pe_ratio"] > 0]
    # Negative-equity companies are already excluded entirely above
    # (see the candidate-building loop) -- everything reaching this
    # point has non-negative Debt/Equity, so ROE and D/E don't need a
    # separate exclusion here.
    roe_values = [c["roe_pct"] for c in candidates]
    de_values = [c["debt_to_equity"] for c in candidates]
    growth_values = [c["sales_cagr_pct"] for c in candidates]

    for c in candidates:
        # P/E ranking excludes negative or zero values entirely -- those
        # signal a loss-making company, not "cheap." Caught live: a
        # stock with P/E -1.86 and ROE -72.75% ranked #1 before this
        # fix, because naive lower-is-better ranking scored -1.86 as
        # the single best P/E in the whole batch (numerically smallest
        # = "cheapest"), when it actually means the company lost money
        # that year. Treating it as not-applicable here lets the
        # correctly-bad ROE actually pull the combined rank down
        # instead of being masked by an artificially perfect P/E score.
        pe = c["pe_ratio"]
        c["pe_rank"] = _percentile_rank(pe_values, pe, lower_is_better=True) if (pe is not None and pe > 0) else None
        c["roe_rank"] = _percentile_rank(roe_values, c["roe_pct"], lower_is_better=False)
        c["debt_equity_rank"] = _percentile_rank(de_values, c["debt_to_equity"], lower_is_better=True)
        c["growth_rank"] = _percentile_rank(growth_values, c["sales_cagr_pct"], lower_is_better=False)

        ranks = [r for r in (c["pe_rank"], c["roe_rank"], c["debt_equity_rank"], c["growth_rank"]) if r is not None]
        c["combined_fundamentals_rank"] = round(sum(ranks) / len(ranks), 1) if ranks else None

    candidates = [c for c in candidates if c["combined_fundamentals_rank"] is not None]
    candidates.sort(key=lambda c: c["combined_fundamentals_rank"], reverse=True)
    return candidates[:top_n]


if __name__ == "__main__":
    results = build_watchlist()
    if not results:
        print("No stocks currently match (need to be meaningfully below their 52-week high, and have both fundamentals + price data). This is expected with only a small test batch of data so far -- not a bug.")
    else:
        print(f"{len(results)} stock(s) match, ranked best-first by combined fundamentals:\n")
        for i, c in enumerate(results, 1):
            print(f"{i}. {c['symbol']} ({c['company_name']})")
            print(f"   {c['pct_off_52w_high']}% off 52-week high | P/E {c['pe_ratio']} | ROE {c['roe_pct']}% | D/E {c['debt_to_equity']} | Sales CAGR {c['sales_cagr_pct']}%")
            print(f"   Combined fundamentals rank: {c['combined_fundamentals_rank']}/100")
            print()
