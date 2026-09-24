from rest_framework import serializers
from .models import (
    ResearchCompany, ResearchSnapshot, FinancialSnapshot, QuarterlyFinancialSnapshot,
    BalanceSheetSnapshot, CashFlowSnapshot, ValuationSnapshot, OwnershipSnapshot,
    SegmentSnapshot, CorporateActivity, ResearchNewsItem, ResearchReport, ResearchMetric,
)


class ResearchCompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = ResearchCompany
        fields = ['symbol', 'company_name', 'isin', 'sector', 'industry', 'exchange', 'market_cap', 'listing_date']


class FinancialSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancialSnapshot
        exclude = ['id', 'snapshot']


class QuarterlyFinancialSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuarterlyFinancialSnapshot
        exclude = ['id', 'snapshot']


class BalanceSheetSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = BalanceSheetSnapshot
        exclude = ['id', 'snapshot']


class CashFlowSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashFlowSnapshot
        exclude = ['id', 'snapshot']


class ValuationSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = ValuationSnapshot
        exclude = ['id', 'snapshot']


class OwnershipSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = OwnershipSnapshot
        exclude = ['id', 'snapshot']


class SegmentSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = SegmentSnapshot
        exclude = ['id', 'snapshot']


class CorporateActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = CorporateActivity
        exclude = ['id', 'snapshot']


class ResearchNewsItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResearchNewsItem
        exclude = ['id', 'snapshot']


class ResearchReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResearchReport
        exclude = ['id', 'snapshot']


class ResearchSnapshotDetailSerializer(serializers.ModelSerializer):
    """The full 'everything about this snapshot' payload -- backs
    GET /api/research/company/{symbol}/report/."""
    company = ResearchCompanySerializer(read_only=True)
    financials = FinancialSnapshotSerializer(many=True, read_only=True)
    quarterly_financials = QuarterlyFinancialSnapshotSerializer(many=True, read_only=True)
    balance_sheets = BalanceSheetSnapshotSerializer(many=True, read_only=True)
    cash_flows = CashFlowSnapshotSerializer(many=True, read_only=True)
    valuation = ValuationSnapshotSerializer(read_only=True)
    ownership = OwnershipSnapshotSerializer(read_only=True)
    segments = SegmentSnapshotSerializer(many=True, read_only=True)
    corporate_activity = CorporateActivitySerializer(many=True, read_only=True)
    news_items = ResearchNewsItemSerializer(many=True, read_only=True)
    report = ResearchReportSerializer(read_only=True)

    class Meta:
        model = ResearchSnapshot
        fields = [
            'id', 'company', 'snapshot_date', 'triggered_by', 'created_at',
            'financials', 'quarterly_financials', 'balance_sheets', 'cash_flows',
            'valuation', 'ownership', 'segments', 'corporate_activity', 'news_items', 'report',
        ]


class ResearchSnapshotListSerializer(serializers.ModelSerializer):
    """Lighter payload for GET /api/research/{symbol}/history/ -- just
    enough to list past snapshots, not the full nested tree."""
    class Meta:
        model = ResearchSnapshot
        fields = ['id', 'snapshot_date', 'triggered_by', 'created_at']
