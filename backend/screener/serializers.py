from rest_framework import serializers
from .models import Stock, StockSnapshot, Signal, MarketOverview

class StockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stock
        fields = ['id', 'symbol', 'name', 'sector', 'is_fno', 'lot_size', 'created_at']

class StockSnapshotSerializer(serializers.ModelSerializer):
    stock = StockSerializer(read_only=True)
    class Meta:
        model = StockSnapshot
        fields = '__all__'

class SignalSerializer(serializers.ModelSerializer):
    stock = StockSerializer(read_only=True)
    class Meta:
        model = Signal
        fields = [
            'id', 'stock', 'score', 'grade', 'signal_type', 'option_type',
            'strike', 'entry', 'stop_loss', 'target_1', 'target_2', 'target_3',
            'risk_reward', 'confidence', 'pcr', 'max_pain', 'iv', 'oi_buildup',
            'trend', 'is_active', 'created_at', 'expires_at',
            'prediction_1d', 'prediction_3d', 'prediction_confidence'
        ]

class MarketOverviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketOverview
        fields = '__all__'