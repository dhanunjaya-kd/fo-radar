"""
backend/fundamentals_research/services/averaging_calculator.py

Sep 26 2026. Pure math, deliberately -- per the spec this was built
against: "Validate all averaging calculations independently" and "Do
not automatically recommend averaging simply because the stock is
down." No AI, no LLM call, no model persistence (this is a stateless
calculator -- the user's holding details are theirs, not something
this app stores). Every number here traces to a documented formula in
this file's own docstrings, nothing estimated.
"""
from dataclasses import dataclass, asdict
from typing import Optional, List


@dataclass
class AveragingScenario:
    label: str
    additional_qty: float
    additional_investment: float
    new_total_qty: float
    new_total_invested: float
    new_weighted_avg_price: float
    exposure_increase_pct: float
    breakeven_price: float
    unrealized_pnl_at_current_price: float
    unrealized_pnl_pct_at_current_price: float


class AveragingInputError(ValueError):
    """Raised for genuinely invalid input (negative quantity, zero
    price, etc.) -- distinct from a missing/optional field, which is
    handled by the caller deciding whether to ask for it or compute a
    labeled hypothetical instead (per spec: "If the user's holding
    details are missing, ask for the required inputs or provide a
    clearly labeled hypothetical calculation")."""
    pass


def calculate_current_position(existing_avg_price: float, existing_qty: float, current_price: float) -> dict:
    """
    The baseline, before any averaging scenario is applied.

    holding_value = qty * current_price
    invested = qty * avg_price
    unrealized_pnl = holding_value - invested
    """
    if existing_avg_price <= 0 or existing_qty <= 0 or current_price <= 0:
        raise AveragingInputError("existing_avg_price, existing_qty, and current_price must all be positive.")

    invested = existing_qty * existing_avg_price
    holding_value = existing_qty * current_price
    pnl = holding_value - invested
    pnl_pct = (pnl / invested * 100) if invested else 0.0

    return {
        'existing_qty': existing_qty,
        'existing_avg_price': round(existing_avg_price, 2),
        'current_price': round(current_price, 2),
        'invested_capital': round(invested, 2),
        'current_holding_value': round(holding_value, 2),
        'unrealized_pnl': round(pnl, 2),
        'unrealized_pnl_pct': round(pnl_pct, 2),
    }


def calculate_averaging_scenario(
    existing_avg_price: float, existing_qty: float, current_price: float,
    additional_qty: Optional[float] = None, additional_investment: Optional[float] = None,
    label: str = "Scenario",
) -> AveragingScenario:
    """
    Exactly one of additional_qty / additional_investment must be
    given -- the other is derived from current_price. Never both (that
    would be an over-specified, potentially inconsistent input) and
    never neither.

    new_weighted_avg = (existing_qty*existing_avg_price + additional_qty*current_price)
                        / (existing_qty + additional_qty)
    breakeven_price = new_weighted_avg (before transaction costs --
                        the spec's own explicit phrasing: "price
                        required to break even before costs")
    exposure_increase_pct = additional_investment / existing_invested_capital * 100
    """
    if existing_avg_price <= 0 or existing_qty <= 0 or current_price <= 0:
        raise AveragingInputError("existing_avg_price, existing_qty, and current_price must all be positive.")

    has_qty = additional_qty is not None
    has_amount = additional_investment is not None
    if has_qty == has_amount:
        raise AveragingInputError("Provide exactly one of additional_qty or additional_investment, not both or neither.")

    if has_amount:
        if additional_investment <= 0:
            raise AveragingInputError("additional_investment must be positive.")
        additional_qty = additional_investment / current_price
    else:
        if additional_qty <= 0:
            raise AveragingInputError("additional_qty must be positive.")
        additional_investment = additional_qty * current_price

    existing_invested = existing_qty * existing_avg_price
    new_total_qty = existing_qty + additional_qty
    new_total_invested = existing_invested + additional_investment
    new_weighted_avg = new_total_invested / new_total_qty

    current_value_at_new_qty = new_total_qty * current_price
    pnl_at_current = current_value_at_new_qty - new_total_invested
    pnl_pct_at_current = (pnl_at_current / new_total_invested * 100) if new_total_invested else 0.0

    exposure_increase_pct = (additional_investment / existing_invested * 100) if existing_invested else 0.0

    return AveragingScenario(
        label=label,
        additional_qty=round(additional_qty, 4),
        additional_investment=round(additional_investment, 2),
        new_total_qty=round(new_total_qty, 4),
        new_total_invested=round(new_total_invested, 2),
        new_weighted_avg_price=round(new_weighted_avg, 2),
        exposure_increase_pct=round(exposure_increase_pct, 2),
        breakeven_price=round(new_weighted_avg, 2),
        unrealized_pnl_at_current_price=round(pnl_at_current, 2),
        unrealized_pnl_pct_at_current_price=round(pnl_pct_at_current, 2),
    )


def calculate_downside_scenarios(new_total_qty: float, new_total_invested: float, price_levels: List[float]) -> List[dict]:
    """
    "Downside scenarios at selected price levels" -- per spec Section
    4. Takes the ALREADY-COMPUTED post-averaging position (from
    calculate_averaging_scenario above) and shows real P&L at each
    hypothetical price the user supplies. Never generates its own
    price levels -- the caller (or the user) supplies them; this
    function only does the arithmetic, matching the "do not generate
    arbitrary...levels" discipline applied everywhere else in this app.
    """
    results = []
    for price in price_levels:
        if price <= 0:
            continue
        value_at_price = new_total_qty * price
        pnl = value_at_price - new_total_invested
        pnl_pct = (pnl / new_total_invested * 100) if new_total_invested else 0.0
        results.append({
            'price': round(price, 2),
            'position_value': round(value_at_price, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
        })
    return results


def scenario_to_dict(scenario: AveragingScenario) -> dict:
    return asdict(scenario)
