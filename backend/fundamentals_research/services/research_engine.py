"""
backend/fundamentals_research/services/research_engine.py

The orchestrator. One public entry point -- run_research(symbol) --
that does exactly the pipeline described in spec Section 23:
fetch -> normalize -> calculate -> persist -> (report_builder builds
the narrative separately, kept as its own module per Section 5's
requested service-layer split).

Fallback chain implemented literally as Section 7 describes:
BharatStock -> Screener -> N/A. Never invents a value. Every DB write
below tags source + retrieved_at, because the models themselves
require it (non-nullable on every fact table).
"""
import logging
from datetime import datetime, date, timezone as dt_timezone
from decimal import Decimal
from typing import Optional

from django.utils import timezone as django_timezone
from django.db import transaction

from . import bharatstock_client as bsc
from . import screener_fallback as sf
from . import financial_analysis as fa
from . import ownership_analysis as oa
from . import valuation_analysis as va
from . import news_analysis as na
from .source_registry import SourcedValue, Source

logger = logging.getLogger('fundamentals_research.research_engine')


class ResearchUnavailableError(Exception):
    """Raised only when BOTH BharatStock and Screener fail entirely --
    i.e. there is genuinely nothing to build a snapshot from, not even
    a partial one. A partial result (some sections populated, others
    None) is NOT this error -- that's a normal, valid snapshot with
    honest gaps, handled by the report builder's N/A rendering, not by
    raising."""
    pass


def _sv_to_decimal(sv: Optional[SourcedValue]):
    if sv is None or sv.value is None:
        return None
    try:
        return Decimal(str(sv.value))
    except Exception:
        return None


def _fetch_bharatstock_bundle(symbol: str) -> Optional[dict]:
    """Every individual BharatStock call is wrapped separately -- one
    endpoint failing (say, insider-trades 404ing because the INFERRED
    path is wrong) must not take down the whole bundle when get_stock()
    and get_financials() succeeded fine. Matches spec Section 27: "if
    one section fails, the entire research report should NOT crash."
    """
    bundle = {}
    try:
        raw_stock = bsc.get_stock(symbol)
        bundle['stock'] = bsc.normalize_stock_response(raw_stock)
    except bsc.BharatStockError as e:
        logger.warning(f"BharatStock get_stock failed for {symbol}: {e}")
        return None  # no stock identity at all -> the whole bundle is unusable

    for key, fn, args in [
        ('financials_annual', bsc.get_financials, (symbol, 'annual')),
        ('financials_quarterly', bsc.get_financials, (symbol, 'quarterly')),
        ('insider_trades', bsc.get_insider_trades, (symbol,)),
        ('bulk_deals', bsc.get_bulk_deals, (symbol,)),
        ('block_deals', bsc.get_block_deals, (symbol,)),
        ('corporate_actions', bsc.get_corporate_actions, (symbol,)),
        ('mf_holdings', bsc.get_mf_holdings, (symbol,)),
    ]:
        try:
            bundle[key] = fn(*args)
        except bsc.BharatStockError as e:
            logger.info(f"BharatStock {key} unavailable for {symbol} ({e}) -- section will show N/A, not fabricated.")
            bundle[key] = None
    return bundle


@transaction.atomic
def run_research(symbol: str, triggered_by: str = 'refresh'):
    """
    Returns the newly-created ResearchSnapshot. Raises
    ResearchUnavailableError only if there's nothing at all to work
    with. Import of models is deferred to inside the function so this
    module (and everything it imports) can still be unit-tested
    without Django's app registry being fully loaded, matching how the
    other services/*.py files in this app are structured.
    """
    from ..models import (
        ResearchCompany, ResearchSnapshot, FinancialSnapshot, QuarterlyFinancialSnapshot,
        BalanceSheetSnapshot, CashFlowSnapshot, ValuationSnapshot, OwnershipSnapshot,
        SegmentSnapshot, CorporateActivity, ResearchNewsItem, ResearchMetric,
    )

    symbol = symbol.upper().strip()
    bundle = _fetch_bharatstock_bundle(symbol)
    screener_data = None
    primary_source = Source.BHARATSTOCK

    if bundle is None:
        logger.info(f"BharatStock unavailable for {symbol} -- falling back to existing Screener integration.")
        screener_data = sf.get_screener_fundamentals(symbol)
        primary_source = Source.SCREENER
        if screener_data is None:
            raise ResearchUnavailableError(
                f"Neither BharatStock nor the existing Screener integration returned data for {symbol}. "
                f"No snapshot created -- per spec Section 7/27, this is reported as unavailable, not fabricated."
            )

    company, _ = ResearchCompany.objects.get_or_create(
        symbol=symbol,
        defaults={'bharatstock_symbol': symbol},
    )
    if bundle:
        stock = bundle['stock']
        company.company_name = stock.get('company_name') or company.company_name
        company.isin = stock.get('isin') or company.isin
        company.sector = stock.get('sector') or company.sector
        company.industry = stock.get('industry') or company.industry
        company.exchange = stock.get('exchange') or company.exchange or 'NSE'
        company.save()

    previous_snapshot = ResearchSnapshot.objects.filter(company=company).order_by('-snapshot_date', '-created_at').first()
    previous_metrics = {}
    if previous_snapshot:
        previous_metrics = {m.metric_name: m for m in previous_snapshot.metrics.all()}

    now = django_timezone.now()
    snapshot = ResearchSnapshot.objects.create(company=company, snapshot_date=now.date(), triggered_by=triggered_by)
    metrics_to_record = {}  # metric_name -> (value, unit, period, source), fed into ResearchMetric at the end

    if bundle:
        _persist_bharatstock_financials(snapshot, bundle, FinancialSnapshot, QuarterlyFinancialSnapshot, metrics_to_record, SegmentSnapshot=SegmentSnapshot)

        stock = bundle['stock']
        prev_promoter = None
        if previous_snapshot and hasattr(previous_snapshot, 'ownership'):
            prev_promoter = float(previous_snapshot.ownership.promoter_pct) if previous_snapshot.ownership.promoter_pct is not None else None
        ownership = oa.build_ownership_snapshot(stock.get('ownership', {}), previous_promoter_pct=prev_promoter)
        OwnershipSnapshot.objects.create(
            snapshot=snapshot, as_of_quarter=ownership['as_of_quarter'] or '',
            promoter_pct=_sv_to_decimal(ownership['promoter_pct']),
            promoter_change_pct=_sv_to_decimal(ownership['promoter_change_pct']),
            promoter_pledge_pct=_sv_to_decimal(ownership['promoter_pledge_pct']),
            fii_pct=_sv_to_decimal(ownership['fii_pct']), dii_pct=_sv_to_decimal(ownership['dii_pct']),
            mutual_fund_pct=_sv_to_decimal(ownership['mutual_fund_pct']),
            mutual_fund_scheme_count=ownership['mutual_fund_scheme_count'].value,
            public_pct=_sv_to_decimal(ownership['public_pct']),
            source=Source.BHARATSTOCK, retrieved_at=now,
        )
        if ownership['promoter_pct'].is_available:
            metrics_to_record['promoter_pct'] = (ownership['promoter_pct'].value, '%', ownership['as_of_quarter'], Source.BHARATSTOCK)

        valuation = va.build_valuation_snapshot(stock.get('valuation', {}), stock.get('market', {}))
        ValuationSnapshot.objects.create(
            snapshot=snapshot, as_of_date=now.date(),
            price=_sv_to_decimal(valuation['price']), market_cap=_sv_to_decimal(valuation['market_cap']),
            pe=_sv_to_decimal(valuation['pe']), pb=_sv_to_decimal(valuation['pb']), peg=_sv_to_decimal(valuation['peg']),
            ev_ebitda=_sv_to_decimal(valuation['ev_ebitda']), price_to_sales=_sv_to_decimal(valuation['price_to_sales']),
            dividend_yield_pct=_sv_to_decimal(valuation['dividend_yield_pct']),
            earnings_yield_pct=_sv_to_decimal(valuation['earnings_yield_pct_calculated']),
            week_52_high=_sv_to_decimal(valuation['week_52_high']), week_52_low=_sv_to_decimal(valuation['week_52_low']),
            distance_from_52w_high_pct=_sv_to_decimal(valuation['distance_from_52w_high_pct']),
            dma_50=_sv_to_decimal(valuation['dma_50']), dma_200=_sv_to_decimal(valuation['dma_200']),
            source=Source.BHARATSTOCK, retrieved_at=now,
        )
        for key in ('pe', 'pb', 'market_cap'):
            if valuation[key].is_available:
                metrics_to_record[f'valuation_{key}'] = (valuation[key].value, '', None, Source.BHARATSTOCK)

        # Sep 24 2026: segment persistence used to live here, reading
        # stock.get('segments') -- confirmed via your real response
        # that get_stock() never returns a 'segments' key at all.
        # Real segment data (segment_revenue/segment_results) comes
        # from get_financials() instead, per fiscal period -- now
        # handled inside _persist_bharatstock_financials() itself,
        # called above.

        _persist_corporate_activity(snapshot, bundle, CorporateActivity, now)

    elif screener_data:
        # Fallback path: Screener gives a narrower field set (confirmed
        # in the prior audit -- Sales/EPS/PE/ROE/D-E/OPM/Sales CAGR).
        # Persisted into the SAME FinancialSnapshot/ValuationSnapshot
        # tables, just with fewer fields populated and source=SCREENER
        # instead of BHARATSTOCK -- the report builder reads these
        # tables generically and doesn't need to know which path filled
        # them, only what `source` says.
        period = screener_data['pe_ratio'].period or 'latest'
        FinancialSnapshot.objects.create(
            snapshot=snapshot, fiscal_year=period,
            revenue=_sv_to_decimal(screener_data['sales_cr']), pat=_sv_to_decimal(screener_data['net_profit_cr']),
            eps=_sv_to_decimal(screener_data['eps']), roe_pct=_sv_to_decimal(screener_data['roe_pct']),
            pat_margin_pct=_sv_to_decimal(screener_data['opm_pct']),
            source=Source.SCREENER, retrieved_at=now,
        )
        BalanceSheetSnapshot.objects.create(
            snapshot=snapshot, fiscal_year=period,
            debt_equity=_sv_to_decimal(screener_data['debt_to_equity']),
            source=Source.SCREENER, retrieved_at=now,
        )
        ValuationSnapshot.objects.create(
            snapshot=snapshot, as_of_date=now.date(),
            price=_sv_to_decimal(screener_data['current_price']), pe=_sv_to_decimal(screener_data['pe_ratio']),
            market_cap=_sv_to_decimal(screener_data['market_cap_cr']),
            source=Source.SCREENER, retrieved_at=now,
        )
        for key in ('pe_ratio', 'roe_pct', 'sales_cagr_pct'):
            if screener_data[key].is_available:
                metrics_to_record[f'screener_{key}'] = (screener_data[key].value, '', period, Source.SCREENER)

    company_name_for_news = (bundle['stock'].get('company_name') if bundle else (screener_data['company_name'].value if screener_data else '')) or ''
    for item in na.get_company_news(symbol, company_name_for_news):
        ResearchNewsItem.objects.create(snapshot=snapshot, **item)

    what_changed = _diff_metrics(previous_metrics, metrics_to_record) if previous_snapshot else None
    for name, (value, unit, period, source) in metrics_to_record.items():
        ResearchMetric.objects.create(snapshot=snapshot, metric_name=name, metric_value=value, unit=unit, period=period or '', source=source)

    return snapshot, what_changed, primary_source


def _persist_bharatstock_financials(snapshot, bundle, FinancialSnapshot, QuarterlyFinancialSnapshot, metrics_to_record, SegmentSnapshot=None):
    """
    Sep 24 2026 -- REWRITTEN against your real WIPRO response, not
    guessed a second time. Real shape: {"data": [...], "pagination": {...}},
    newest-first confirmed (2025-26 before 2024-25 in your actual
    output). Each row is FLAT -- P&L (revenue/ebitda/net_profit/eps),
    balance sheet (total_assets/current_assets/current_liabilities/
    cash_and_cash_equivalents/borrowings_current/borrowings_non_current/
    total_equity), and cash flow (cash_flow_operating/cash_flow_investing/
    cash_flow_financing/capex) all live on the SAME per-period row --
    not in separate sub-objects the way the original guess assumed.
    Segment data (segment_revenue/segment_results) is ALSO on this same
    row, confirmed real -- previously assumed (wrongly) to come from
    get_stock() instead, where it doesn't exist at all.
    """
    annual = (bundle.get('financials_annual') or {}).get('data') or []
    for i, period_data in enumerate(annual):
        fy = period_data.get('fiscal_year') or f'FY-{i}'
        revenue = SourcedValue(period_data.get('revenue'), Source.BHARATSTOCK, period=fy)
        ebitda = SourcedValue(period_data.get('ebitda'), Source.BHARATSTOCK, period=fy)
        pat = SourcedValue(period_data.get('net_profit'), Source.BHARATSTOCK, period=fy)
        eps = SourcedValue(period_data.get('eps'), Source.BHARATSTOCK, period=fy)
        equity = SourcedValue(period_data.get('total_equity'), Source.BHARATSTOCK, period=fy)

        prior_period = annual[i + 1] if i + 1 < len(annual) else None
        prior_revenue = SourcedValue(prior_period.get('revenue') if prior_period else None, Source.BHARATSTOCK)
        prior_pat = SourcedValue(prior_period.get('net_profit') if prior_period else None, Source.BHARATSTOCK)

        ebitda_margin = fa.calculate_margin_pct(ebitda, revenue, period=fy)
        pat_margin = fa.calculate_margin_pct(pat, revenue, period=fy)
        roe = fa.calculate_roe_pct(pat, equity, period=fy)
        rev_growth = fa.calculate_growth_pct(revenue, prior_revenue, period=fy)
        pat_growth = fa.calculate_growth_pct(pat, prior_pat, period=fy)

        FinancialSnapshot.objects.create(
            snapshot=snapshot, fiscal_year=fy,
            revenue=_sv_to_decimal(revenue), revenue_growth_yoy_pct=_sv_to_decimal(rev_growth),
            ebitda=_sv_to_decimal(ebitda), ebitda_margin_pct=_sv_to_decimal(ebitda_margin),
            pat=_sv_to_decimal(pat), pat_margin_pct=_sv_to_decimal(pat_margin), pat_growth_yoy_pct=_sv_to_decimal(pat_growth),
            eps=_sv_to_decimal(eps), roe_pct=_sv_to_decimal(roe),
            source=Source.BHARATSTOCK, retrieved_at=django_timezone.now(),
        )

        # Balance sheet -- one row per fiscal year, same source data as
        # above, not a separate BharatStock call (confirmed: no such
        # call exists -- it's all on this one row).
        if SegmentSnapshot is not None:  # signals the caller passed a real DB layer, not a dry test
            total_debt_val = None
            bc, bnc = period_data.get('borrowings_current'), period_data.get('borrowings_non_current')
            if bc is not None or bnc is not None:
                total_debt_val = (bc or 0) + (bnc or 0)
            debt = SourcedValue(total_debt_val, Source.BHARATSTOCK, period=fy)
            cash = SourcedValue(period_data.get('cash_and_cash_equivalents'), Source.BHARATSTOCK, period=fy)
            current_assets = SourcedValue(period_data.get('current_assets'), Source.BHARATSTOCK, period=fy)
            current_liabilities = SourcedValue(period_data.get('current_liabilities'), Source.BHARATSTOCK, period=fy)
            net_debt = fa.calculate_net_debt(debt, cash)
            debt_equity = fa.calculate_debt_equity(debt, equity)
            current_ratio = fa.calculate_current_ratio(current_assets, current_liabilities)
            working_capital = fa.calculate_working_capital(current_assets, current_liabilities)

            from ..models import BalanceSheetSnapshot, CashFlowSnapshot
            BalanceSheetSnapshot.objects.create(
                snapshot=snapshot, fiscal_year=fy,
                total_debt=_sv_to_decimal(debt), cash=_sv_to_decimal(cash), net_debt=_sv_to_decimal(net_debt),
                total_equity=_sv_to_decimal(equity),
                current_assets=_sv_to_decimal(current_assets), current_liabilities=_sv_to_decimal(current_liabilities),
                working_capital=_sv_to_decimal(working_capital), debt_equity=_sv_to_decimal(debt_equity),
                current_ratio=_sv_to_decimal(current_ratio),
                source=Source.BHARATSTOCK, retrieved_at=django_timezone.now(),
            )

            cfo = SourcedValue(period_data.get('cash_flow_operating'), Source.BHARATSTOCK, period=fy)
            capex = SourcedValue(period_data.get('capex'), Source.BHARATSTOCK, period=fy)
            fcf = fa.calculate_free_cash_flow(cfo, capex)
            fcf_margin = fa.calculate_margin_pct(fcf, revenue, period=fy)
            cfo_to_pat = fa.calculate_cfo_to_pat(cfo, pat, period=fy)
            capex_intensity = fa.calculate_capex_intensity_pct(capex, revenue, period=fy)
            CashFlowSnapshot.objects.create(
                snapshot=snapshot, fiscal_year=fy,
                operating_cash_flow=_sv_to_decimal(cfo), capex=_sv_to_decimal(capex), free_cash_flow=_sv_to_decimal(fcf),
                investing_cash_flow=period_data.get('cash_flow_investing'), financing_cash_flow=period_data.get('cash_flow_financing'),
                fcf_margin_pct=_sv_to_decimal(fcf_margin), cfo_to_pat=_sv_to_decimal(cfo_to_pat),
                capex_intensity_pct=_sv_to_decimal(capex_intensity),
                source=Source.BHARATSTOCK, retrieved_at=django_timezone.now(),
            )

            # Segments -- confirmed real, lives on this same row (segment_revenue/segment_results),
            # NOT on get_stock() as originally (wrongly) assumed.
            seg_revenue = {s['segment']: s['value'] for s in (period_data.get('segment_revenue') or [])}
            seg_results = {s['segment']: s['value'] for s in (period_data.get('segment_results') or [])}
            total_seg_revenue = sum(v for v in seg_revenue.values() if v)
            for seg_name, seg_rev in seg_revenue.items():
                SegmentSnapshot.objects.create(
                    snapshot=snapshot, fiscal_period=fy, segment_name=seg_name,
                    segment_revenue=seg_rev, segment_result=seg_results.get(seg_name),
                    revenue_contribution_pct=(round(seg_rev / total_seg_revenue * 100, 2) if seg_rev and total_seg_revenue else None),
                    source=Source.BHARATSTOCK, retrieved_at=django_timezone.now(),
                )

            if i == 0:
                for name, sv_ in [('debt_equity', debt_equity), ('fcf', fcf), ('cfo_to_pat', cfo_to_pat)]:
                    if sv_.is_available:
                        metrics_to_record[name] = (sv_.value, '', fy, Source.CALCULATED)

        if i == 0:  # most recent year drives the headline metrics dict
            for name, sv_ in [('revenue', revenue), ('pat', pat), ('eps', eps), ('roe_pct', roe)]:
                if sv_.is_available:
                    metrics_to_record[name] = (sv_.value, '', fy, Source.BHARATSTOCK)

    quarterly = (bundle.get('financials_quarterly') or {}).get('data') or []
    for i, period_data in enumerate(quarterly):
        # Real annual rows confirmed 'quarter': null for annual periods
        # -- for quarterly rows this is expected to hold something like
        # "Q1"; combined with fiscal_year for a real label. Not yet
        # confirmed against a real quarterly response (only annual was
        # fetched) -- falls back to period_end_date if 'quarter' turns
        # out empty, so this degrades to a still-correct (if less
        # pretty) label rather than a blank one.
        q = period_data.get('quarter')
        fy = period_data.get('fiscal_year', '')
        fq = f"{q} FY{fy}" if q else (period_data.get('period_end_date') or f'Q-{i}')
        revenue = SourcedValue(period_data.get('revenue'), Source.BHARATSTOCK, period=fq)
        pat = SourcedValue(period_data.get('net_profit'), Source.BHARATSTOCK, period=fq)
        prior_q_data = quarterly[i + 1] if i + 1 < len(quarterly) else None
        prior_q_revenue = SourcedValue(prior_q_data.get('revenue') if prior_q_data else None, Source.BHARATSTOCK)
        qoq = fa.calculate_growth_pct(revenue, prior_q_revenue, period=fq)
        QuarterlyFinancialSnapshot.objects.create(
            snapshot=snapshot, fiscal_quarter=fq,
            revenue=_sv_to_decimal(revenue), revenue_growth_qoq_pct=_sv_to_decimal(qoq),
            pat=_sv_to_decimal(pat), eps=period_data.get('eps'),
            source=Source.BHARATSTOCK, retrieved_at=django_timezone.now(),
        )


def _persist_corporate_activity(snapshot, bundle, CorporateActivity, now):
    for insider in ((bundle.get('insider_trades') or {}).get('trades') or []):
        CorporateActivity.objects.create(
            snapshot=snapshot, activity_type='insider_trade',
            activity_date=insider.get('date') or now.date(),
            party_name=insider.get('name', ''), party_category=insider.get('category', ''),
            transaction_type=insider.get('transaction_type', ''), quantity=insider.get('quantity'),
            value=insider.get('value'), pre_holding_pct=insider.get('pre_holding_pct'), post_holding_pct=insider.get('post_holding_pct'),
            source=Source.BHARATSTOCK, retrieved_at=now,
        )
    for deal_type, key in [('bulk_deal', 'bulk_deals'), ('block_deal', 'block_deals')]:
        for deal in ((bundle.get(key) or {}).get('deals') or []):
            CorporateActivity.objects.create(
                snapshot=snapshot, activity_type=deal_type,
                activity_date=deal.get('date') or now.date(),
                party_name=deal.get('client_name', ''), transaction_type=deal.get('transaction_type', ''),
                quantity=deal.get('quantity'), price=deal.get('price'), value=deal.get('value'),
                source=Source.BHARATSTOCK, retrieved_at=now,
            )
    for action in ((bundle.get('corporate_actions') or {}).get('actions') or []):
        CorporateActivity.objects.create(
            snapshot=snapshot, activity_type=action.get('type', 'dividend'),
            activity_date=action.get('date') or now.date(),
            ratio_or_amount=action.get('ratio_or_amount', ''),
            source=Source.BHARATSTOCK, retrieved_at=now,
        )


def _diff_metrics(previous: dict, current: dict) -> dict:
    """Generic diff, per spec Section 21 -- works on ANY metric_name
    present in both snapshots, not a hardcoded list of fields to
    compare. Returns {} (not None) when there's simply nothing in
    common yet, distinct from previous_snapshot being None entirely
    (the caller distinguishes 'no previous snapshot' from 'previous
    snapshot had no overlapping metrics' per Section 21's two
    required messages)."""
    changes = {}
    for name, (new_value, unit, period, source) in current.items():
        prev_metric = previous.get(name)
        if prev_metric is None or new_value is None:
            continue
        prev_value = float(prev_metric.metric_value) if prev_metric.metric_value is not None else None
        if prev_value is None:
            continue
        if prev_value == new_value:
            continue
        changes[name] = {
            'previous': prev_value, 'current': float(new_value),
            'change': round(float(new_value) - prev_value, 4),
            'change_pct': round((float(new_value) - prev_value) / abs(prev_value) * 100, 2) if prev_value != 0 else None,
        }
    return changes
