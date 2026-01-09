import websockets
import json
import asyncio
import logging
from typing import Callable, Optional, Dict
import time

logger = logging.getLogger(__name__)

class OKXWebSocketClient:
    """OKX WebSocket client using candle channels directly"""
    
    def __init__(self, symbol: str = "BTC-USDT-SWAP"):
        self.url = "wss://ws.okx.com:8443/ws/v5/public"
        self.symbol = symbol
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_running = False
        self.reconnect_delay = 5
        self.max_reconnect_delay = 60  # Cap at 60 seconds
        self.reconnect_attempts = 0
        
        # Callbacks
        self.on_candle_1m: Optional[Callable] = None
        self.on_candle_5m: Optional[Callable] = None
        self.on_candle_15m: Optional[Callable] = None  # Add 15m callback
        self.on_ticker: Optional[Callable] = None
        self.on_orderbook: Optional[Callable] = None
        self.on_trade: Optional[Callable] = None
        self.on_funding_rate: Optional[Callable] = None
        self.on_mark_price: Optional[Callable] = None
        
        # Track last received data timestamps
        self.last_data_time = {
            'candle_1m': 0,
            'candle_5m': 0,
            'ticker': 0,
            'orderbook': 0,
            'funding': 0
        }
        
        # Connection health tracking
        self.connected_since = None
        self.total_reconnects = 0
        
    def get_health_status(self) -> Dict:
        """Get connection health status for monitoring"""
        now = time.time()
        last_data = max(self.last_data_time.values()) if self.last_data_time else 0
        data_age = now - last_data if last_data > 0 else None
        
        return {
            'connected': self.ws is not None and self.is_running,
            'connected_since': self.connected_since,
            'uptime_seconds': (now - self.connected_since) if self.connected_since else 0,
            'last_data_age_seconds': data_age,
            'total_reconnects': self.total_reconnects,
            'data_stale': data_age is not None and data_age > 30  # Stale if >30s without data
        }
        
    async def connect(self):
        """Connect to OKX WebSocket and subscribe to all channels"""
        while self.is_running:
            try:
                logger.info(f"Connecting to {self.url}...")
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=10) as ws:
                    self.ws = ws
                    logger.info("Connected to OKX WebSocket")
                    
                    # Subscribe to all channels with 300ms delay
                    subscriptions = [
                        {"op": "subscribe", "args": [{"channel": "candle1m", "instId": self.symbol}]},
                        {"op": "subscribe", "args": [{"channel": "candle5m", "instId": self.symbol}]},
                        {"op": "subscribe", "args": [{"channel": "candle15m", "instId": self.symbol}]},
                        {"op": "subscribe", "args": [{"channel": "tickers", "instId": self.symbol}]},
                        {"op": "subscribe", "args": [{"channel": "books", "instId": self.symbol}]},
                        {"op": "subscribe", "args": [{"channel": "trades", "instId": self.symbol}]},
                        {"op": "subscribe", "args": [{"channel": "funding-rate", "instId": self.symbol}]},
                        {"op": "subscribe", "args": [{"channel": "mark-price", "instId": self.symbol}]}
                    ]
                    
                    for msg in subscriptions:
                        await ws.send(json.dumps(msg))
                        await asyncio.sleep(0.3)
                    
                    logger.info(f"Subscribed to all channels for {self.symbol}")
                    
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
            # Log every message for debugging
            arg = data.get('arg', {})
            channel = arg.get('channel', '')
            
            if channel:
                logger.debug(f"Received {channel} message")
            
            if channel == 'candle1m':
                self.last_data_time['candle_1m'] = time.time()
                if self.on_candle_1m and data.get('data'):
                    for candle in data['data']:
                        await self.on_candle_1m(candle)
                        
            elif channel == 'candle5m':
                self.last_data_time['candle_5m'] = time.time()
                if self.on_candle_5m and data.get('data'):
                    for candle in data['data']:
                        await self.on_candle_5m(candle)
                        
            elif channel == 'candle15m':
                if self.on_candle_15m and data.get('data'):
                    for candle in data['data']:
                        await self.on_candle_15m(candle)
                        
            elif channel == 'tickers':
                self.last_data_time['ticker'] = time.time()
                if self.on_ticker and data.get('data'):
                    logger.debug(f"Ticker data: {data['data'][0]}")
                    await self.on_ticker(data['data'][0])
                    
            elif channel == 'books':
                # Full depth orderbook (OKX provides 400 levels by default)
                self.last_data_time['orderbook'] = time.time()
                if self.on_orderbook and data.get('data'):
                    orderbook_data = data['data'][0]
                    bids = orderbook_data.get('bids', [])
                    asks = orderbook_data.get('asks', [])
                    logger.debug(f"Orderbook received - bids: {len(bids)}, asks: {len(asks)}")
                    await self.on_orderbook(orderbook_data)
                    
            elif channel == 'trades':
                if self.on_trade and data.get('data'):
                    for trade in data['data']:
                        await self.on_trade(trade)
                        
            elif channel == 'funding-rate':
                self.last_data_time['funding'] = time.time()
                if self.on_funding_rate and data.get('data'):
                    logger.debug(f"Funding rate: {data['data'][0].get('fundingRate')}")
                    await self.on_funding_rate(data['data'][0])
                    
            elif channel == 'mark-price':
                if self.on_mark_price and data.get('data'):
                    await self.on_mark_price(data['data'][0])
                    
        except Exception as e:
            logger.error(f"Error routing message: {e}, data: {data}")
    
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
    
    def get_health_status(self) -> Dict:
        """Get health status of data streams"""
        current_time = time.time()
        return {
            'candle_1m_age': current_time - self.last_data_time['candle_1m'],
            'candle_5m_age': current_time - self.last_data_time['candle_5m'],
            'ticker_age': current_time - self.last_data_time['ticker'],
            'orderbook_age': current_time - self.last_data_time['orderbook'],
            'funding_age': current_time - self.last_data_time['funding']
        }
