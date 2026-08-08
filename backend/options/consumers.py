import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

class OptionsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.symbol = self.scope["url_route"]["kwargs"]["symbol"]
        self.group_name = f"options_{self.symbol}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        if data.get("action") == "subscribe_strikes":
            await self.send(text_data=json.dumps({"type": "subscribed", "symbol": self.symbol}))

    async def option_update(self, event):
        await self.send(text_data=json.dumps({"type": "option_update", "data": event["data"]}))
