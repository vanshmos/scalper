import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from bybit_client import OKXWebSocketClient
from candle_builder import CandleBuilder
from indicators import Indicators

logger = logging.getLogger(__name__)

class SignalEngine:
    def __init__(self):
        self.candle_builder = CandleBuilder()
        self.indicators = Indicators()
        self.ws_client = OKXWebSocketClient(
            on_orderbook=self.on_orderbook,
            on_trade=self.on_trade,
            on_ticker=self.on_ticker
        )
        self.is_connected = False
        self.last_orderbook: Optional[dict] = None
        self.last_ticker: Optional[dict] = None
        self.last_update_time = None
        
        # Track recent trades for CVD calculation
        self.recent_trades: List[dict] = []
        self.max_trade_history = 500  # Keep last 500 trades (~5 minutes at high volume)
    
    async def on_orderbook(self, data: dict):
        """Handle orderbook updates"""
        try:
            self.last_orderbook = data
            self.last_update_time = datetime.now(timezone.utc)
        except Exception as e:
            logger.error(f"Error handling orderbook: {e}")
    
    async def on_trade(self, trade: dict):
        """Handle trade updates"""
        try:
            await self.candle_builder.on_trade(trade)
            self.last_update_time = datetime.now(timezone.utc)
        except Exception as e:
            logger.error(f"Error handling trade: {e}")
    
    async def on_ticker(self, data: dict):
        """Handle ticker updates"""
        try:
            self.last_ticker = data
            self.last_update_time = datetime.now(timezone.utc)
        except Exception as e:
            logger.error(f"Error handling ticker: {e}")
    
    async def start(self):
        """Start the signal engine"""
        logger.info("Starting signal engine...")
        self.is_connected = True
        await self.ws_client.start()
    
    async def stop(self):
        """Stop the signal engine"""
        logger.info("Stopping signal engine...")
        self.is_connected = False
        await self.ws_client.stop()
        self.candle_builder.save_to_file()
    
    def get_status(self) -> dict:
        """Get current engine status"""
        candle_status = self.candle_builder.get_status()
        
        return {
            'connected': self.is_connected,
            'last_update': self.last_update_time.isoformat() if self.last_update_time else None,
            'current_price': candle_status['current_price'],
            'candle_counts': candle_status['candle_counts']
        }
