"""News views for F&O Sniper."""
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.http import JsonResponse


@api_view(['GET'])
def news_list(request):
    """Return news list - safe fallback if table doesn't exist."""
    try:
        from .models import NewsItem
        news = NewsItem.objects.all().order_by('-published_at')[:20]
        data = [{
            "id": n.id,
            "title": n.title,
            "source": n.source,
            "published_at": n.published_at.isoformat() if n.published_at else None,
            "sentiment": n.sentiment
        } for n in news]
        return Response(data)
    except Exception as e:
        print(f"News error: {e}")
        return Response([], status=200)


@api_view(['GET'])
def news_detail(request, pk):
    """Return single news item."""
    try:
        from .models import NewsItem
        item = NewsItem.objects.get(pk=pk)
        return Response({
            "id": item.id,
            "title": item.title,
            "source": item.source,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "sentiment": item.sentiment
        })
    except Exception as e:
        return Response({"error": str(e)}, status=404)


@api_view(['GET'])
def fetch_news(request):
    """Fetch latest news - safe fallback."""
    try:
        from .models import NewsItem
        news = NewsItem.objects.all().order_by('-published_at')[:10]
        data = [{
            "id": n.id,
            "title": n.title,
            "source": n.source,
            "published_at": n.published_at.isoformat() if n.published_at else None,
            "sentiment": n.sentiment
        } for n in news]
        return Response({"status": "success", "count": len(data), "data": data})
    except Exception as e:
        print(f"Fetch news error: {e}")
        return Response({"status": "success", "count": 0, "data": []}, status=200)