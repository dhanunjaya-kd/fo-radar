from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import BacktestResult
from .integration import BacktestIntegration

@api_view(['GET'])
def backtest_results(request):
    results = BacktestResult.objects.all().order_by('-created_at')[:10]
    data = [{
        "strategy": r.strategy_name, "start": str(r.start_date),
        "total_signals": r.total_signals, "win_rate": r.win_rate,
        "total_pnl": r.total_pnl, "created_at": r.created_at.isoformat(),
    } for r in results]
    return Response(data)

@api_view(['POST'])
def sync_backtest(request):
    integration = BacktestIntegration()
    success = integration.sync_to_db()
    return Response({"synced": success})

@api_view(['GET'])
def backtest_metrics(request):
    integration = BacktestIntegration()
    return Response(integration.get_performance_metrics())
