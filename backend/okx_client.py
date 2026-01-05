import websockets
import json
import asyncio
import logging
from typing import Callable, Optional, Dict

logger = logging.getLogger(__name__)

class OKXWebSocketClient:
    def __init__(self, on_orderbook: Callable, on_trade: Callable, on_ticker: Callable):
        self.url = "wss://ws.okx.com:8443/ws/v5/public"
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.on_orderbook = on_orderbook
        self.on_trade = on_trade
        self.on_ticker = on_ticker
        self.is_running = False
        self.reconnect_delay = 5
        
        # Multi-symbol support
        self.instruments = ['BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP']
        
    async def connect(self):
        """Connect to OKX WebSocket and subscribe to channels"""
        while self.is_running:
            try:
                logger.info(f"Connecting to {self.url}...")
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=10) as ws:
                    self.ws = ws
                    logger.info("Connected to OKX WebSocket")
                    
                    # Subscribe to channels for all instruments with 300ms delay
                    for instrument in self.instruments:
                        subscribe_messages = [
                            {"op": "subscribe", "args": [{"channel": "trades", "instId": instrument}]},
                            {"op": "subscribe", "args": [{"channel": "books", "instId": instrument}]},
                            {"op": "subscribe", "args": [{"channel": "tickers", "instId": instrument}]},
                            {"op": "subscribe", "args": [{"channel": "mark-price", "instId": instrument}]}
                        ]
                        
                        for msg in subscribe_messages:
                            await ws.send(json.dumps(msg))
                            await asyncio.sleep(0.3)  # 300ms delay
                    
                    logger.info(f"Subscribed to all channels for {len(self.instruments)} instruments")
                    
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
            # OKX message format: {arg: {channel, instId}, data: [...]}
            arg = data.get('arg', {})
            channel = arg.get('channel', '')
            inst_id = arg.get('instId', '')
            
            # Extract symbol from instId (BTC-USDT-SWAP -> BTC)
            symbol = inst_id.split('-')[0] if inst_id else None
            
            if not symbol:
                return
            
            if channel == 'books':
                # Orderbook updates
                books_data = data.get('data', [])
                if books_data:
                    await self.on_orderbook(symbol, books_data[0])
            elif channel == 'trades':
                # Trade updates
                trades = data.get('data', [])
                for trade in trades:
                    await self.on_trade(symbol, trade)
            elif channel == 'tickers':
                # Ticker updates
                ticker_data = data.get('data', [])
                if ticker_data:
                    await self.on_ticker(symbol, ticker_data[0])
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
