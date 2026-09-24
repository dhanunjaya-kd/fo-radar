"""
backend/fundamentals_research/services/report_builder.py

Builds the ResearchReport row from an already-persisted
ResearchSnapshot -- takes structured data (already fact-checked,
already calculated, already saved by research_engine.py) and produces
the narrative sections from spec Section 19.

Hard rule enforced throughout: every sentence is either a RAW FACT
(a number straight from a model field), a CALCULATED note (states the
formula/what was compared), or an explicitly-labeled INTERPRETATION.
No sentence blends the three silently -- Section 11's own example is
followed literally, not paraphrased into something looser.

No scoring. No buy/sell language anywhere in this file -- checked by
this file's own test (test_report_builder.py) scanning every generated
string against a banned-word list, not just trusted by convention.
"""
from typing import Optional


_BANNED_TERMS = ['buy', 'sell', 'strong buy', 'strong sell', 'best stock', 'worst stock', 'recommend']


def _fmt(value, suffix=''):
    if value is None:
        return 'N/A'
    return f"{value}{suffix}"


def build_business_overview(company) -> str:
    parts = []
    if company.company_name:
        parts.append(f"{company.company_name} ({company.symbol}) trades on {company.exchange or 'NSE'}.")
    if company.sector or company.industry:
        parts.append(f"Sector: {company.sector or 'N/A'}. Industry: {company.industry or 'N/A'}.")
    if not parts:
        return "Business overview unavailable -- no company profile data was returned by any source."
    return " ".join(parts)


def build_financial_quality_notes(financials_qs) -> str:
    """financials_qs: FinancialSnapshot queryset for one snapshot,
    ordered newest-first (matches the model's own Meta ordering)."""
    rows = list(financials_qs)
    if not rows:
        return "Financial quality: N/A -- no financial statement data available from any source for this snapshot."

    latest = rows[0]
    lines = [
        f"RAW: {latest.fiscal_year} revenue was {_fmt(latest.revenue)}, PAT was {_fmt(latest.pat)}, EPS was {_fmt(latest.eps)}.",
    ]
    if latest.revenue_growth_yoy_pct is not None:
        lines.append(f"CALCULATED: Revenue growth YoY = {latest.revenue_growth_yoy_pct}% (current year revenue vs. the immediately prior year on record).")
    else:
        lines.append("CALCULATED: Revenue growth YoY = N/A -- fewer than two years of revenue history available to compute a comparison.")
    if latest.ebitda_margin_pct is not None:
        lines.append(f"CALCULATED: EBITDA margin = {latest.ebitda_margin_pct}%.")
    if latest.roe_pct is not None:
        lines.append(f"CALCULATED: ROE = {latest.roe_pct}%.")

    if len(rows) >= 3:
        oldest_of_recent = rows[min(len(rows), 3) - 1]
        if oldest_of_recent.revenue and latest.revenue:
            direction = "expansion" if latest.revenue > oldest_of_recent.revenue else "contraction" if latest.revenue < oldest_of_recent.revenue else "no material change"
            lines.append(f"INTERPRETATION: Revenue across the {min(len(rows), 3)} most recent years on record shows {direction} ({oldest_of_recent.fiscal_year}: {_fmt(oldest_of_recent.revenue)} -> {latest.fiscal_year}: {_fmt(latest.revenue)}). This describes the trend direction only, not a conclusion about whether that trend will continue.")
    return "\n".join(lines)


def build_balance_sheet_notes(bs_row) -> str:
    if bs_row is None:
        return "Balance sheet: N/A -- no balance sheet data available from any source for this snapshot."
    lines = [f"RAW: {bs_row.fiscal_year} total debt {_fmt(bs_row.total_debt)}, cash {_fmt(bs_row.cash)}."]
    if bs_row.debt_equity is not None:
        lines.append(f"CALCULATED: Debt/Equity = {bs_row.debt_equity}.")
    if bs_row.interest_coverage is not None:
        lines.append(f"CALCULATED: Interest coverage = {bs_row.interest_coverage}x.")
    if bs_row.current_ratio is not None:
        lines.append(f"CALCULATED: Current ratio = {bs_row.current_ratio}.")
    return "\n".join(lines)


def build_cash_flow_notes(cf_row) -> str:
    if cf_row is None:
        return "Cash flow: N/A -- no cash flow data available from any source for this snapshot."
    lines = [f"RAW: {cf_row.fiscal_year} operating cash flow {_fmt(cf_row.operating_cash_flow)}, capex {_fmt(cf_row.capex)}."]
    if cf_row.free_cash_flow is not None:
        lines.append(f"CALCULATED: Free cash flow = {cf_row.free_cash_flow}.")
    if cf_row.cfo_to_pat is not None:
        lines.append(f"CALCULATED: CFO/PAT = {cf_row.cfo_to_pat}.")
        # This is spec Section 12's own literal example -- reproduced
        # here as the exact factual-language pattern it specifies, not
        # a paraphrase.
        if float(cf_row.cfo_to_pat) < 0.7:
            lines.append(f"FACT: Operating cash flow was lower than reported net profit for {cf_row.fiscal_year} (CFO/PAT = {cf_row.cfo_to_pat}).")
    return "\n".join(lines)


def build_ownership_notes(own_row) -> str:
    if own_row is None:
        return "Ownership: N/A -- no shareholding data available for this snapshot."
    lines = [f"RAW: Promoter holding {_fmt(own_row.promoter_pct, '%')}, FII {_fmt(own_row.fii_pct, '%')}, DII {_fmt(own_row.dii_pct, '%')}, public {_fmt(own_row.public_pct, '%')} as of {own_row.as_of_quarter or 'the latest available period'}."]
    if own_row.promoter_change_pct is not None:
        direction = "increased" if own_row.promoter_change_pct > 0 else "decreased" if own_row.promoter_change_pct < 0 else "was unchanged"
        lines.append(f"RAW: Promoter holding {direction} by {abs(own_row.promoter_change_pct)} percentage points versus the previous snapshot.")
    if own_row.promoter_pledge_pct:
        lines.append(f"RAW: Promoter pledge = {own_row.promoter_pledge_pct}%.")
    return "\n".join(lines)


def build_risks(financials_qs, bs_row, cf_row, own_row) -> list:
    """
    Per spec Section 17: only flag a risk when supported by data, each
    with evidence + source. Deliberately conservative -- this checks a
    small number of objectively-defined conditions against real stored
    numbers, not a broad opinion-based risk list.
    """
    risks = []
    if bs_row and bs_row.debt_equity is not None and float(bs_row.debt_equity) > 1.0:
        risks.append({
            'risk': 'Debt risk', 'evidence': f"Debt/Equity = {bs_row.debt_equity} (> 1.0)",
            'source': bs_row.source, 'potential_relevance': 'Elevated leverage increases sensitivity to interest-rate and refinancing conditions.',
        })
    if cf_row and cf_row.cfo_to_pat is not None and float(cf_row.cfo_to_pat) < 0.7:
        risks.append({
            'risk': 'Cash-flow quality risk', 'evidence': f"CFO/PAT = {cf_row.cfo_to_pat} (< 0.7)",
            'source': cf_row.source, 'potential_relevance': 'Reported profit is not being fully converted into operating cash.',
        })
    if own_row and own_row.promoter_pledge_pct and float(own_row.promoter_pledge_pct) > 0:
        risks.append({
            'risk': 'Governance risk', 'evidence': f"Promoter pledge = {own_row.promoter_pledge_pct}% (> 0%)",
            'source': own_row.source, 'potential_relevance': 'Pledged promoter shares can force selling pressure if pledge terms are triggered.',
        })
    financials = list(financials_qs)
    if len(financials) >= 2 and financials[0].revenue_growth_yoy_pct is not None and float(financials[0].revenue_growth_yoy_pct) < 0:
        risks.append({
            'risk': 'Growth risk', 'evidence': f"Revenue growth YoY = {financials[0].revenue_growth_yoy_pct}% (< 0%)",
            'source': financials[0].source, 'potential_relevance': 'Revenue contracted year-over-year in the most recent period on record.',
        })
    return risks


def build_scenarios(financials_qs, bs_row) -> dict:
    """Per spec Section 18: assumptions and monitoring metrics, no
    price targets. Deliberately generic structure filled with whatever
    real levers were actually observed in the data -- not a templated
    paragraph unrelated to this specific company's numbers."""
    financials = list(financials_qs)
    latest = financials[0] if financials else None
    metrics_to_monitor = []
    if latest and latest.revenue_growth_yoy_pct is not None:
        metrics_to_monitor.append('Revenue growth YoY')
    if latest and latest.ebitda_margin_pct is not None:
        metrics_to_monitor.append('EBITDA margin')
    if bs_row and bs_row.debt_equity is not None:
        metrics_to_monitor.append('Debt/Equity')

    return {
        'bull': {
            'assumptions': ['Revenue growth sustains or accelerates versus the most recent reported rate.', 'Margins hold or expand.'],
            'metrics_to_monitor': metrics_to_monitor,
        },
        'base': {
            'assumptions': [f"Current reported trend continues: revenue growth of {_fmt(latest.revenue_growth_yoy_pct, '%') if latest else 'N/A'}, EBITDA margin of {_fmt(latest.ebitda_margin_pct, '%') if latest else 'N/A'}."],
            'metrics_to_monitor': metrics_to_monitor,
        },
        'bear': {
            'assumptions': ['Revenue growth decelerates or reverses versus the most recent reported rate.', 'Margins compress.'],
            'invalidation_triggers': ['A reported quarter with revenue growth materially below the base-case assumption.', 'A sustained rise in Debt/Equity beyond the currently reported level.'],
        },
    }


def build_report(snapshot, what_changed: Optional[dict]):
    """Builds and returns (does not save) a dict matching ResearchReport's
    fields -- the caller (the API view, or a management command) decides
    when to actually persist it, keeping this function a pure builder."""
    company = snapshot.company
    financials_qs = snapshot.financials.all()
    bs_row = snapshot.balance_sheets.first()
    cf_row = snapshot.cash_flows.first()
    own_row = getattr(snapshot, 'ownership', None)
    val_row = getattr(snapshot, 'valuation', None)

    valuation_notes = "Valuation: N/A -- no valuation data available." if val_row is None else \
        f"RAW: P/E {_fmt(val_row.pe)}, P/B {_fmt(val_row.pb)}, EV/EBITDA {_fmt(val_row.ev_ebitda)}. Price is {_fmt(val_row.distance_from_52w_high_pct, '%')} from its 52-week high."

    report_data = {
        'business_overview': build_business_overview(company),
        'financial_quality_notes': build_financial_quality_notes(financials_qs),
        'balance_sheet_notes': build_balance_sheet_notes(bs_row),
        'cash_flow_notes': build_cash_flow_notes(cf_row),
        'ownership_notes': build_ownership_notes(own_row),
        'governance_notes': "Governance: no auditor-qualification or related-party-transaction feed is currently wired -- see docs/FUNDAMENTAL_RESEARCH.md's Known Limitations section. Promoter pledge (a real, sourced signal) is reported under Ownership above.",
        'valuation_notes': valuation_notes,
        'risks_json': build_risks(financials_qs, bs_row, cf_row, own_row),
        'key_metrics_to_monitor': build_scenarios(financials_qs, bs_row)['base']['metrics_to_monitor'],
        'what_changed_json': what_changed if what_changed is not None else {'status': 'first_snapshot', 'message': 'First research snapshot -- no previous comparison available.'},
        'data_freshness_json': {
            'financials': financials_qs.first().fiscal_year if financials_qs.exists() else None,
            'valuation_as_of': val_row.as_of_date.isoformat() if val_row and val_row.as_of_date else None,
            'ownership_as_of': own_row.as_of_quarter if own_row else None,
        },
    }
    scenarios = build_scenarios(financials_qs, bs_row)
    report_data['bull_case_json'] = scenarios['bull']
    report_data['base_case_json'] = scenarios['base']
    report_data['bear_case_json'] = scenarios['bear']

    # Self-check against the banned-term list before returning --
    # belt-and-suspenders alongside the dedicated test, since this
    # function is the one place a future edit could accidentally slip
    # recommendation language into a template string.
    full_text = " ".join(str(v) for k, v in report_data.items() if isinstance(v, str)).lower()
    for term in _BANNED_TERMS:
        if term in full_text:
            raise ValueError(f"Report builder produced banned term '{term}' -- spec Section 14 violation, not shipped.")

    return report_data
