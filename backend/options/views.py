from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import OptionChain
from screener.models import Signal

@api_view(['GET'])
def option_chain(request, symbol):
    """Get option chain for a symbol."""
    from django.utils import timezone
    from datetime import timedelta
    chains = OptionChain.objects.filter(
        stock__symbol=symbol,
        timestamp__gte=timezone.now() - timedelta(hours=1)
    ).order_by('strike')
    data = [{
        'strike': c.strike, 'expiry': c.expiry,
        'ce_ltp': c.ce_ltp, 'ce_oi': c.ce_oi, 'ce_oi_chg': c.ce_oi_chg, 'ce_iv': c.ce_iv,
        'pe_ltp': c.pe_ltp, 'pe_oi': c.pe_oi, 'pe_oi_chg': c.pe_oi_chg, 'pe_iv': c.pe_iv,
        'pcr': c.pcr
    } for c in chains]
    return Response(data)

@api_view(['GET'])
def options_dive(request, symbol):
    """Full options analytics for a symbol (matches WARRENER detail view)."""
    try:
        signal = Signal.objects.get(stock__symbol=symbol, is_active=True)
        return Response({
            'symbol': symbol, 'ltp': signal.stock.snapshots.first().ltp if signal.stock.snapshots.exists() else 0,
            'score': signal.score, 'grade': signal.grade, 'signal_type': signal.signal_type,
            'option_type': signal.option_type, 'strike': signal.strike,
            'entry': signal.entry, 'stop_loss': signal.stop_loss,
            'target_1': signal.target_1, 'target_2': signal.target_2, 'target_3': signal.target_3,
            'risk_reward': signal.risk_reward, 'confidence': signal.confidence,
            'pcr': signal.pcr, 'max_pain': signal.max_pain, 'iv': signal.iv,
            'oi_buildup': signal.oi_buildup, 'trend': signal.trend,
            'prediction_1d': signal.prediction_1d,
            'prediction_3d': signal.prediction_3d,
            'prediction_confidence': signal.prediction_confidence,
        })
    except Signal.DoesNotExist:
        return Response({"error": "No active signal"}, status=404)
