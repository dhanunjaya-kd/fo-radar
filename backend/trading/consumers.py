import json
from channels.generic.websocket import AsyncWebsocketConsumer

class AlertsConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for trade alerts"""

    async def connect(self):
        self.room_group_name = 'trade_alerts'
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        await self.send(text_data=json.dumps({
            'type': 'connection',
            'status': 'connected',
            'channel': 'trade_alerts'
        }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def trade_alert(self, event):
        await self.send(text_data=json.dumps({
            'type': 'trade_alert',
            'data': event['data']
        }))

    async def pnl_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'pnl_update',
            'data': event['data']
        }))
