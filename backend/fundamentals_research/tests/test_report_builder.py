from django.test import TestCase
from django.utils import timezone

from fundamentals_research.models import (
    ResearchCompany, ResearchSnapshot, FinancialSnapshot, BalanceSheetSnapshot,
    CashFlowSnapshot, OwnershipSnapshot,
)
from fundamentals_research.services import report_builder as rb
from fundamentals_research.services.source_registry import Source


class TestReportBuilder(TestCase):
    def setUp(self):
        self.company = ResearchCompany.objects.create(symbol='RELIANCE', company_name='Reliance Industries Limited', sector='Energy', industry='Refineries')
        self.snapshot = ResearchSnapshot.objects.create(company=self.company, snapshot_date=timezone.now().date())
        FinancialSnapshot.objects.create(
            snapshot=self.snapshot, fiscal_year='FY2025-26', revenue=900000, revenue_growth_yoy_pct=5.88,
            ebitda=150000, ebitda_margin_pct=16.67, pat=74000, roe_pct=9.25,
            source=Source.BHARATSTOCK, retrieved_at=timezone.now(),
        )
        FinancialSnapshot.objects.create(
            snapshot=self.snapshot, fiscal_year='FY2024-25', revenue=850000,
            source=Source.BHARATSTOCK, retrieved_at=timezone.now(),
        )

    def test_business_overview_uses_real_company_fields(self):
        overview = rb.build_business_overview(self.company)
        self.assertIn('Reliance Industries Limited', overview)
        self.assertIn('Energy', overview)

    def test_financial_quality_notes_has_fact_calculated_interpretation_structure(self):
        notes = rb.build_financial_quality_notes(self.snapshot.financials.all())
        self.assertIn('RAW:', notes)
        self.assertIn('CALCULATED:', notes)
        self.assertIn('5.88', notes)  # the real stored growth figure, not recomputed here

    def test_missing_balance_sheet_returns_honest_na_not_crash(self):
        notes = rb.build_balance_sheet_notes(None)
        self.assertIn('N/A', notes)

    def test_cfo_below_pat_produces_the_exact_spec_example_sentence(self):
        cf = CashFlowSnapshot.objects.create(
            snapshot=self.snapshot, fiscal_year='FY2025-26', operating_cash_flow=30000, capex=10000,
            free_cash_flow=20000, cfo_to_pat=0.3,  # genuinely low, should trigger the flagged sentence
            source=Source.BHARATSTOCK, retrieved_at=timezone.now(),
        )
        notes = rb.build_cash_flow_notes(cf)
        self.assertIn('Operating cash flow was lower than reported net profit', notes)  # spec Section 12's literal required phrasing

    def test_risks_only_flagged_with_real_evidence(self):
        bs = BalanceSheetSnapshot.objects.create(
            snapshot=self.snapshot, fiscal_year='FY2025-26', debt_equity=1.5,  # > 1.0, should flag
            source=Source.BHARATSTOCK, retrieved_at=timezone.now(),
        )
        risks = rb.build_risks(self.snapshot.financials.all(), bs, None, None)
        debt_risks = [r for r in risks if r['risk'] == 'Debt risk']
        self.assertEqual(len(debt_risks), 1)
        self.assertIn('1.5', debt_risks[0]['evidence'])
        self.assertEqual(debt_risks[0]['source'], Source.BHARATSTOCK)

    def test_no_risk_flagged_when_debt_equity_is_healthy(self):
        bs = BalanceSheetSnapshot.objects.create(
            snapshot=self.snapshot, fiscal_year='FY2025-26', debt_equity=0.3,  # healthy, should NOT flag
            source=Source.BHARATSTOCK, retrieved_at=timezone.now(),
        )
        risks = rb.build_risks(self.snapshot.financials.all(), bs, None, None)
        debt_risks = [r for r in risks if r['risk'] == 'Debt risk']
        self.assertEqual(len(debt_risks), 0)

    def test_full_report_build_never_contains_banned_recommendation_language(self):
        report_data = rb.build_report(self.snapshot, what_changed=None)
        full_text = " ".join(str(v) for v in report_data.values() if isinstance(v, str)).lower()
        for term in rb._BANNED_TERMS:
            self.assertNotIn(term, full_text, f"Report contained banned term: {term}")

    def test_first_snapshot_what_changed_is_the_exact_spec_message(self):
        report_data = rb.build_report(self.snapshot, what_changed=None)
        self.assertEqual(report_data['what_changed_json']['message'], 'First research snapshot -- no previous comparison available.')

    def test_what_changed_passed_through_when_present(self):
        changed = {'revenue': {'previous': 850000, 'current': 900000, 'change': 50000, 'change_pct': 5.88}}
        report_data = rb.build_report(self.snapshot, what_changed=changed)
        self.assertEqual(report_data['what_changed_json'], changed)
