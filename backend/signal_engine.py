import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from bybit_client import OKXWebSocketClient
from candle_builder import CandleBuilder
from indicators import Indicators
from regime import RegimeDetector

logger = logging.getLogger(__name__)

class SignalEngine:
    def __init__(self):
        self.candle_builder = CandleBuilder()
        self.indicators = Indicators()
        self.regime_detector = RegimeDetector()
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
            
            # Store trade for CVD calculation
            self.recent_trades.append(trade)
            if len(self.recent_trades) > self.max_trade_history:
                self.recent_trades.pop(0)
            
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
        
        # Calculate indicators
        try:
            # EMA calculations
            ema20_1m = self.indicators.calculate_ema(self.candle_builder.candles_1m, 20)
            ema50_1m = self.indicators.calculate_ema(self.candle_builder.candles_1m, 50)
            
            ema20_5m = self.indicators.calculate_ema(self.candle_builder.candles_5m, 20)
            ema50_5m = self.indicators.calculate_ema(self.candle_builder.candles_5m, 50)
            
            ema20_15m = self.indicators.calculate_ema(self.candle_builder.candles_15m, 20)
            ema50_15m = self.indicators.calculate_ema(self.candle_builder.candles_15m, 50)
            
            # ATR and RSI on 5m
            atr_5m = self.indicators.calculate_atr(self.candle_builder.candles_5m, 14)
            rsi_5m = self.indicators.calculate_rsi(self.candle_builder.candles_5m, 14)
            
            # Orderbook indicators
            obi = None
            spread = None
            depth = None
            if self.last_orderbook:
                obi = self.indicators.calculate_obi(self.last_orderbook)
                spread = self.indicators.calculate_spread(self.last_orderbook)
                depth = self.indicators.calculate_depth(self.last_orderbook)
            
            # CVD calculations
            cvd_1m = self.indicators.calculate_cvd(self.recent_trades, 60)
            cvd_5m = self.indicators.calculate_cvd(self.recent_trades, 300)
            
            # Regime detection
            regime = self.regime_detector.detect_regime(
                self.candle_builder.candles_5m,
                self.candle_builder.candles_15m,
                ema20_5m, ema50_5m,
                ema20_15m, ema50_15m,
                atr_5m
            )
            
            # Gates check
            gates = self.regime_detector.get_gates_status(spread, depth)
            
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            ema20_1m = ema50_1m = ema20_5m = ema50_5m = ema20_15m = ema50_15m = None
            atr_5m = rsi_5m = obi = spread = depth = cvd_1m = cvd_5m = None
        
        return {
            'connected': self.is_connected,
            'last_update': self.last_update_time.isoformat() if self.last_update_time else None,
            'current_price': candle_status['current_price'],
            'candle_counts': candle_status['candle_counts'],
            'indicators': {
                'ema': {
                    '1m': {'ema20': ema20_1m, 'ema50': ema50_1m},
                    '5m': {'ema20': ema20_5m, 'ema50': ema50_5m},
                    '15m': {'ema20': ema20_15m, 'ema50': ema50_15m}
                },
                'atr_5m': atr_5m,
                'rsi_5m': rsi_5m,
                'obi': obi,
                'spread': spread,
                'depth': depth,
                'cvd': {
                    '1m': cvd_1m,
                    '5m': cvd_5m
                }
            }
        }
