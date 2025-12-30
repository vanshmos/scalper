import websockets
import json
import asyncio
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

class BybitWebSocketClient:
    def __init__(self, on_orderbook: Callable, on_trade: Callable, on_ticker: Callable):
        self.url = "wss://stream.bybit.com/v5/public/linear"
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.on_orderbook = on_orderbook
        self.on_trade = on_trade
        self.on_ticker = on_ticker
        self.is_running = False
        self.reconnect_delay = 5
        
    async def connect(self):
        """Connect to Bybit WebSocket and subscribe to channels"""
        while self.is_running:
            try:
                logger.info(f"Connecting to {self.url}...")
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=10) as ws:
                    self.ws = ws
                    logger.info("Connected to Bybit WebSocket")
                    
                    # Subscribe to channels
                    subscribe_msg = {
                        "op": "subscribe",
                        "args": [
                            "orderbook.50.BTCUSDT",
                            "publicTrade.BTCUSDT",
                            "tickers.BTCUSDT"
                        ]
                    }
                    await ws.send(json.dumps(subscribe_msg))
                    logger.info("Subscribed to channels")
                    
                    # Listen for messages
                    async for message in ws:
                        try:
                            data = json.loads(message)
                            await self._handle_message(data)
                        except json.JSONDecodeError as e:
                            logger.error(f"JSON decode error: {e}")
                        except Exception as e:
                            logger.error(f"Error handling message: {e}")
                            
            except websockets.exceptions.WebSocketException as e:
                logger.error(f"WebSocket error: {e}")
                if self.is_running:
                    logger.info(f"Reconnecting in {self.reconnect_delay} seconds...")
                    await asyncio.sleep(self.reconnect_delay)
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                if self.is_running:
                    logger.info(f"Reconnecting in {self.reconnect_delay} seconds...")
                    await asyncio.sleep(self.reconnect_delay)
    
    async def _handle_message(self, data: dict):
        """Route messages to appropriate handlers"""
        try:
            topic = data.get('topic', '')
            
            if topic.startswith('orderbook'):
                await self.on_orderbook(data.get('data', {}))
            elif topic.startswith('publicTrade'):
                trades = data.get('data', [])
                for trade in trades:
                    await self.on_trade(trade)
            elif topic.startswith('tickers'):
                await self.on_ticker(data.get('data', {}))
        except Exception as e:
            logger.error(f"Error routing message: {e}")
    
    async def start(self):
        """Start the WebSocket client"""
        self.is_running = True
        await self.connect()
    
    async def stop(self):
        """Stop the WebSocket client"""
        self.is_running = False
        if self.ws:
            await self.ws.close()
            logger.info("WebSocket connection closed")
