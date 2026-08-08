from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.utils import timezone
from datetime import timedelta
from .models import PaperTrade, PnLSummary
from .paper_trading import PaperTradingEngine
from .telegram_bot import TelegramAlertBot

@api_view(['POST'])
def create_paper_trade(request):
    data = request.data
    engine = PaperTradingEngine()
    trade = engine.execute_trade(
        symbol=data.get("symbol"),
        option_type=data.get("option_type", "CE"),
        strike=data.get("strike", 0),
        entry_price=data.get("entry_price", 0),
        qty=data.get("qty", 1),
        stop_loss=data.get("stop_loss", 0),
        target_1=data.get("target_1", 0),
        target_2=data.get("target_2"),
        target_3=data.get("target_3"),
    )
    return Response({"id": trade.id, "status": trade.status, "created_at": trade.created_at})

@api_view(['GET'])
def list_paper_trades(request):
    status_filter = request.GET.get("status", "")
    trades = PaperTrade.objects.all()
    if status_filter:
        trades = trades.filter(status=status_filter)
    data = [{
        "id": t.id, "symbol": t.stock.symbol, "option_type": t.option_type,
        "entry": t.entry_price, "sl": t.stop_loss, "target_1": t.target_1,
        "status": t.status, "pnl": t.pnl, "pnl_pct": t.pnl_pct,
        "created_at": t.created_at.isoformat(),
    } for t in trades.order_by('-created_at')[:50]]
    return Response(data)

@api_view(['GET'])
def pnl_summary(request):
    from django.db.models import Sum, Avg, Count, Q
    today = timezone.now().date()

    trades = PaperTrade.objects.filter(created_at__date=today)
    total = trades.count()
    wins = trades.filter(pnl__gt=0).count()
    losses = trades.filter(pnl__lt=0).count()
    total_pnl = trades.aggregate(Sum('pnl'))['pnl__sum'] or 0

    return Response({
        "date": str(today),
        "total_trades": total,
        "winning_trades": wins,
        "losing_trades": losses,
        "total_pnl": total_pnl,
        "win_rate": round((wins / total * 100), 2) if total > 0 else 0,
    })

@api_view(['GET'])
def today_pnl(request):
    engine = PaperTradingEngine()
    return Response({"today_pnl": engine.get_today_pnl()})

@api_view(['POST'])
def test_telegram(request):
    bot = TelegramAlertBot()
    result = bot.send_message("🧪 <b>Test Alert</b>\nF&O Radar Telegram bot is working!")
    return Response({"sent": result is not None})
