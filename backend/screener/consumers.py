import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Signal, MarketOverview
from .serializers import SignalSerializer, MarketOverviewSerializer
from .fyers_client import is_authenticated, get_quotes


class ScreenerConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("screener", self.channel_name)
        await self.accept()
        signals = await self.get_top_signals()
        fyers_status = is_authenticated()
        await self.send(text_data=json.dumps({
            "type": "init",
            "signals": signals,
            "fyers_connected": fyers_status
        }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("screener", self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get("action")
        if action == "filter":
            signals = await self.get_filtered_signals(data.get("filter", {}))
            await self.send(text_data=json.dumps({"type": "filtered", "signals": signals}))
        elif action == "fyers_status":
            await self.send(text_data=json.dumps({
                "type": "fyers_status",
                "connected": is_authenticated()
            }))

    async def signal_update(self, event):
        await self.send(text_data=json.dumps({"type": "update", "signal": event["data"]}))

    @database_sync_to_async
    def get_top_signals(self):
        signals = Signal.objects.filter(is_active=True).order_by('-score')[:50]
        return SignalSerializer(signals, many=True).data

    @database_sync_to_async
    def get_filtered_signals(self, filters):
        qs = Signal.objects.filter(is_active=True)
        if filters.get("signal_type"):
            qs = qs.filter(signal_type=filters["signal_type"])
        if filters.get("grade"):
            qs = qs.filter(grade=filters["grade"])
        if filters.get("min_score"):
            qs = qs.filter(score__gte=filters["min_score"])
        return SignalSerializer(qs.order_by('-score')[:50], many=True).data


class AlertConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("alerts", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("alerts", self.channel_name)

    async def alert_message(self, event):
        await self.send(text_data=json.dumps({"type": "alert", "message": event["data"]}))


class MarketOverviewConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("market_overview", self.channel_name)
        await self.accept()
        overview = await self.get_overview()
        fyers_status = is_authenticated()
        await self.send(text_data=json.dumps({
            "type": "overview",
            "data": overview,
            "fyers_connected": fyers_status
        }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("market_overview", self.channel_name)

    async def overview_update(self, event):
        await self.send(text_data=json.dumps({"type": "overview_update", "data": event["data"]}))

    @database_sync_to_async
    def get_overview(self):
        latest = MarketOverview.objects.first()
        return MarketOverviewSerializer(latest).data if latest else {}