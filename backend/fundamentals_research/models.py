"""
backend/fundamentals_research/models.py

Isolated from the existing fundamentals/ screening app on purpose --
that one is a weekly, full-universe ranking batch job with no DB
models (flat JSON file). This app is a different use case: on-demand,
single-company deep research, with real history (Section 16/21 of the
spec this was built against: "what changed since my previous
research?"). Sharing tables between the two would couple two things
that change on different schedules for different reasons.

Design principle applied throughout: a ResearchSnapshot is the
envelope for "everything we knew about this company at this moment."
Every fact-bearing child table points at a snapshot, not directly at
the company -- so history is just "more rows," never an overwrite.
Every child table also carries `source` and `retrieved_at` on every
row: the spec's Section 20 requirement (source traceability) is
enforced by the schema shape itself, not left to application code to
remember.
"""
from django.db import models


class SourceChoices(models.TextChoices):
    """Mirrors services/source_registry.py's SOURCE constants exactly
    -- kept as an explicit enum here (not a free-text field) so a typo
    in a source name can't silently create an unrecognized source."""
    BHARATSTOCK = 'bharatstock', 'BharatStock'
    SCREENER = 'screener', 'Screener.in (existing client)'
    FYERS = 'fyers', 'Fyers (existing integration)'
    COMPANY_IR = 'company_ir', 'Company IR / exchange filing (manual link)'
    NEWS = 'news', 'News (existing NewsAPI/RSS)'
    CALCULATED = 'calculated', 'Calculated internally from stored raw data'


class ResearchCompany(models.Model):
    symbol = models.CharField(max_length=32, unique=True, db_index=True)
    company_name = models.CharField(max_length=255, blank=True)
    isin = models.CharField(max_length=20, blank=True)
    sector = models.CharField(max_length=128, blank=True)
    industry = models.CharField(max_length=128, blank=True)
    exchange = models.CharField(max_length=16, blank=True, default='NSE')
    market_cap = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    listing_date = models.DateField(null=True, blank=True)
    # Sep 24 2026: existing project's own symbol conventions --
    # fundamentals/symbol_master.py already resolves the Fyers form
    # ("NSE:RELIANCE-EQ"); BharatStock's own symbol form is plain
    # ("RELIANCE") per the verified endpoint shape. Stored separately
    # rather than derived every time, since the derivation rule isn't
    # guaranteed 1:1 for every symbol (see symbol_master.py's own
    # honest caveat about this).
    fyers_symbol = models.CharField(max_length=48, blank=True)
    bharatstock_symbol = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Research companies'

    def __str__(self):
        return self.symbol


class ResearchSnapshot(models.Model):
    """One row per 'research this company right now' event. Every
    other fact table below points here, not at ResearchCompany
    directly -- that's what makes 'compare snapshot N vs N-1'
    (Section 21) a normal query instead of a special case."""
    company = models.ForeignKey(ResearchCompany, on_delete=models.CASCADE, related_name='snapshots')
    snapshot_date = models.DateField(db_index=True)
    triggered_by = models.CharField(max_length=16, default='refresh', help_text="'initial' or 'refresh'")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-snapshot_date', '-created_at']
        indexes = [models.Index(fields=['company', '-snapshot_date'])]

    def __str__(self):
        return f"{self.company.symbol} @ {self.snapshot_date}"


class FinancialSnapshot(models.Model):
    """Annual financial-statement rows. One ResearchSnapshot can (and
    per the verified BharatStock response, currently does) contain
    MULTIPLE rows here -- one per fiscal year returned (2, per the
    live-verified response as of this build; see the client's own
    docstring for that exact number, not repeated here so this file
    doesn't go stale if BharatStock's coverage grows)."""
    snapshot = models.ForeignKey(ResearchSnapshot, on_delete=models.CASCADE, related_name='financials')
    fiscal_year = models.CharField(max_length=16, help_text="e.g. 'FY2025-26'")
    revenue = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    revenue_growth_yoy_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    ebitda = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    ebitda_margin_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    ebit = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    pat = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    pat_margin_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    pat_growth_yoy_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    eps = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    eps_growth_yoy_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    roe_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    roce_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=16, choices=SourceChoices.choices)
    retrieved_at = models.DateTimeField()

    class Meta:
        ordering = ['-fiscal_year']


class QuarterlyFinancialSnapshot(models.Model):
    """Same shape as FinancialSnapshot, separate table rather than a
    'period_type' flag on one shared table -- annual and quarterly
    rows have genuinely different QoQ vs YoY growth semantics, and the
    spec (Section 19/21) treats them as distinct report sections, not
    one filtered view of the same list."""
    snapshot = models.ForeignKey(ResearchSnapshot, on_delete=models.CASCADE, related_name='quarterly_financials')
    fiscal_quarter = models.CharField(max_length=16, help_text="e.g. 'Q1 FY2026-27'")
    revenue = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    revenue_growth_qoq_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    revenue_growth_yoy_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    ebitda = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    ebitda_margin_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    pat = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    pat_margin_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    eps = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    source = models.CharField(max_length=16, choices=SourceChoices.choices)
    retrieved_at = models.DateTimeField()

    class Meta:
        ordering = ['-fiscal_quarter']


class BalanceSheetSnapshot(models.Model):
    snapshot = models.ForeignKey(ResearchSnapshot, on_delete=models.CASCADE, related_name='balance_sheets')
    fiscal_year = models.CharField(max_length=16)
    total_debt = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    cash = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    net_debt = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    equity_capital = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    reserves = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    total_equity = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    current_assets = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    current_liabilities = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    working_capital = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    inventory = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    receivables = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    payables = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    debt_equity = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    current_ratio = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    interest_coverage = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=16, choices=SourceChoices.choices)
    retrieved_at = models.DateTimeField()

    class Meta:
        ordering = ['-fiscal_year']


class CashFlowSnapshot(models.Model):
    snapshot = models.ForeignKey(ResearchSnapshot, on_delete=models.CASCADE, related_name='cash_flows')
    fiscal_year = models.CharField(max_length=16)
    operating_cash_flow = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    investing_cash_flow = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    financing_cash_flow = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    capex = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    free_cash_flow = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    fcf_margin_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    cfo_to_pat = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    capex_intensity_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=16, choices=SourceChoices.choices)
    retrieved_at = models.DateTimeField()

    class Meta:
        ordering = ['-fiscal_year']


class ValuationSnapshot(models.Model):
    snapshot = models.OneToOneField(ResearchSnapshot, on_delete=models.CASCADE, related_name='valuation')
    as_of_date = models.DateField()
    price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    market_cap = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    pe = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    pb = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    peg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    ev_ebitda = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    price_to_sales = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    dividend_yield_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    earnings_yield_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    fcf_yield_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    week_52_high = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    week_52_low = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    distance_from_52w_high_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    dma_50 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    dma_200 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=16, choices=SourceChoices.choices)
    retrieved_at = models.DateTimeField()


class OwnershipSnapshot(models.Model):
    snapshot = models.OneToOneField(ResearchSnapshot, on_delete=models.CASCADE, related_name='ownership')
    as_of_quarter = models.CharField(max_length=16, blank=True)
    promoter_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    promoter_change_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    promoter_pledge_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    fii_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    fii_change_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    dii_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    dii_change_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    mutual_fund_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    mutual_fund_scheme_count = models.IntegerField(null=True, blank=True)
    public_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=16, choices=SourceChoices.choices)
    retrieved_at = models.DateTimeField()


class SegmentSnapshot(models.Model):
    snapshot = models.ForeignKey(ResearchSnapshot, on_delete=models.CASCADE, related_name='segments')
    fiscal_period = models.CharField(max_length=16)
    segment_name = models.CharField(max_length=128)
    segment_revenue = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    segment_result = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    revenue_contribution_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=16, choices=SourceChoices.choices)
    retrieved_at = models.DateTimeField()


class CorporateActivity(models.Model):
    """Covers corporate actions, insider/promoter trades, and bulk/
    block deals in one table -- distinguished by `activity_type`
    rather than three near-identical tables, since all four share the
    same real shape: a dated event with a party, a quantity/value, and
    a source. Splitting further would just mean four copies of the
    same five columns."""
    ACTIVITY_TYPES = [
        ('dividend', 'Dividend'), ('bonus', 'Bonus Issue'), ('split', 'Stock Split'),
        ('rights', 'Rights Issue'), ('insider_trade', 'Insider/Promoter Trade'),
        ('bulk_deal', 'Bulk Deal'), ('block_deal', 'Block Deal'),
    ]
    snapshot = models.ForeignKey(ResearchSnapshot, on_delete=models.CASCADE, related_name='corporate_activity')
    activity_type = models.CharField(max_length=16, choices=ACTIVITY_TYPES)
    activity_date = models.DateField()
    party_name = models.CharField(max_length=255, blank=True)
    party_category = models.CharField(max_length=64, blank=True, help_text="e.g. 'promoter', 'FII', client name for deals")
    transaction_type = models.CharField(max_length=16, blank=True, help_text="buy/sell/acquire/dispose")
    quantity = models.BigIntegerField(null=True, blank=True)
    value = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    ratio_or_amount = models.CharField(max_length=64, blank=True, help_text="for dividends/bonus/splits")
    pre_holding_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    post_holding_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=16, choices=SourceChoices.choices)
    retrieved_at = models.DateTimeField()

    class Meta:
        verbose_name_plural = 'Corporate activity'
        ordering = ['-activity_date']


class ResearchNewsItem(models.Model):
    SENTIMENT_CHOICES = [('positive', 'Positive'), ('negative', 'Negative'), ('neutral', 'Neutral')]
    snapshot = models.ForeignKey(ResearchSnapshot, on_delete=models.CASCADE, related_name='news_items')
    headline = models.CharField(max_length=512)
    url = models.URLField(max_length=1024)
    published_at = models.DateTimeField(null=True, blank=True)
    news_source = models.CharField(max_length=128, blank=True, help_text="the publication, e.g. 'Moneycontrol' -- distinct from SourceChoices, which tracks OUR data pipeline source")
    summary = models.TextField(blank=True)
    sentiment = models.CharField(max_length=8, choices=SENTIMENT_CHOICES, blank=True)
    sentiment_basis = models.TextField(blank=True, help_text="why this sentiment was assigned, per spec Section 16 -- never a bare label with no reasoning")

    class Meta:
        ordering = ['-published_at']


class ResearchMetric(models.Model):
    """Generic (metric_name, value) rows, one row per tracked metric
    per snapshot -- this is what makes Section 21's 'what changed
    since last time' a single generic query (diff this snapshot's
    rows against the previous snapshot's rows by metric_name) instead
    of bespoke comparison code for every individual field on every
    other table above. The typed tables above remain the source of
    truth for the report itself; this table exists purely to make
    cross-snapshot diffing uniform."""
    snapshot = models.ForeignKey(ResearchSnapshot, on_delete=models.CASCADE, related_name='metrics')
    metric_name = models.CharField(max_length=64, db_index=True)
    metric_value = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    unit = models.CharField(max_length=16, blank=True)
    period = models.CharField(max_length=16, blank=True)
    source = models.CharField(max_length=16, choices=SourceChoices.choices)

    class Meta:
        indexes = [models.Index(fields=['snapshot', 'metric_name'])]


class ResearchReport(models.Model):
    """The assembled, human-readable report for one snapshot --
    everything above is structured data; this is the narrative built
    from it. One-to-one with ResearchSnapshot: a snapshot without a
    report yet is a real, valid state (data collected, report
    generation still running or failed partway)."""
    snapshot = models.OneToOneField(ResearchSnapshot, on_delete=models.CASCADE, related_name='report')
    business_overview = models.TextField(blank=True)
    financial_quality_notes = models.TextField(blank=True)
    balance_sheet_notes = models.TextField(blank=True)
    cash_flow_notes = models.TextField(blank=True)
    ownership_notes = models.TextField(blank=True)
    governance_notes = models.TextField(blank=True)
    valuation_notes = models.TextField(blank=True)
    risks_json = models.JSONField(default=list, blank=True)
    bull_case_json = models.JSONField(default=dict, blank=True)
    base_case_json = models.JSONField(default=dict, blank=True)
    bear_case_json = models.JSONField(default=dict, blank=True)
    key_metrics_to_monitor = models.JSONField(default=list, blank=True)
    what_changed_json = models.JSONField(default=dict, blank=True, help_text="empty dict if this is the first-ever snapshot for this company")
    data_freshness_json = models.JSONField(default=dict, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)
