import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from bybit_client import OKXWebSocketClient
from candle_builder import CandleBuilder
from indicators import Indicators
from regime import RegimeDetector
from signal_detector import SignalDetector
from state_machine import SignalStateMachine
from alerts import AlertManager
import time

logger = logging.getLogger(__name__)

class SignalEngine:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.candle_builder = CandleBuilder(symbol)
        self.indicators = Indicators()
        self.regime_detector = RegimeDetector()
        self.signal_detector = SignalDetector()
        self.state_machine = SignalStateMachine()
        self.alert_manager = AlertManager()
        self.is_connected = False
        self.last_orderbook: Optional[dict] = None
        self.last_ticker: Optional[dict] = None
        self.last_update_time = None
        
        # Track recent trades for CVD calculation
        self.recent_trades: List[dict] = []
        self.max_trade_history = 500  # Keep last 500 trades (~5 minutes at high volume)
        
        # Debug mode
        self.debug = False  # Disabled after audit
        self.last_heartbeat_time = 0
        self.heartbeat_interval = 60  # seconds
    
    async def on_orderbook(self, data: dict):
        """Handle orderbook updates"""
        try:
            self.last_orderbook = data
            self.last_update_time = datetime.now(timezone.utc)
        except Exception as e:
            logger.error(f"Error handling orderbook for {self.symbol}: {e}")
    
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
            logger.error(f"Error handling trade for {self.symbol}: {e}")
    
    async def on_ticker(self, data: dict):
        """Handle ticker updates"""
        try:
            self.last_ticker = data
            self.last_update_time = datetime.now(timezone.utc)
        except Exception as e:
            logger.error(f"Error handling ticker for {self.symbol}: {e}")
    
    async def start(self):
        """Start the signal engine"""
        logger.info(f"Starting signal engine for {self.symbol}...")
        self.is_connected = True
    
    async def stop(self):
        """Stop the signal engine"""
        logger.info(f"Stopping signal engine for {self.symbol}...")
        self.is_connected = False
        self.candle_builder.save_to_file()
    
    def _heartbeat_log(self, candle_status: dict, ema20_5m: Optional[float], ema50_5m: Optional[float], 
                       atr_5m: Optional[float], rsi_5m: Optional[float]):
        """Debug heartbeat logger - logs every 60 seconds"""
        current_time = time.time()
        
        if current_time - self.last_heartbeat_time < self.heartbeat_interval:
            return
        
        self.last_heartbeat_time = current_time
        
        logger.info("=" * 80)
        logger.info("HEARTBEAT DIAGNOSTIC LOG")
        logger.info("=" * 80)
        
        # 1. Candle timestamps - last 3 candles
        logger.info("CANDLE TIMESTAMPS (last 3):")
        
        if len(self.candle_builder.candles_1m) > 0:
            last_3_1m = self.candle_builder.candles_1m[-3:] if len(self.candle_builder.candles_1m) >= 3 else self.candle_builder.candles_1m
            logger.info(f"  1m candles: {[datetime.fromtimestamp(c.timestamp).strftime('%H:%M:%S') for c in last_3_1m]}")
        else:
            logger.info(f"  1m candles: []")
        
        if self.candle_builder.current_candle_1m:
            logger.info(f"  Current 1m (building): {datetime.fromtimestamp(self.candle_builder.current_candle_1m.timestamp).strftime('%H:%M:%S')}")
        
        if len(self.candle_builder.candles_5m) > 0:
            last_3_5m = self.candle_builder.candles_5m[-3:] if len(self.candle_builder.candles_5m) >= 3 else self.candle_builder.candles_5m
            logger.info(f"  5m candles: {[datetime.fromtimestamp(c.timestamp).strftime('%H:%M:%S') for c in last_3_5m]}")
        else:
            logger.info(f"  5m candles: []")
        
        if len(self.candle_builder.candles_15m) > 0:
            last_3_15m = self.candle_builder.candles_15m[-3:] if len(self.candle_builder.candles_15m) >= 3 else self.candle_builder.candles_15m
            logger.info(f"  15m candles: {[datetime.fromtimestamp(c.timestamp).strftime('%H:%M:%S') for c in last_3_15m]}")
        else:
            logger.info(f"  15m candles: []")
        
        # 2. Raw indicator inputs
        logger.info("\nRAW INDICATOR INPUTS:")
        
        # RSI input (last 15 close prices from 5m)
        if len(self.candle_builder.candles_5m) > 0:
            last_15_closes_5m = [c.close for c in self.candle_builder.candles_5m[-15:] if c.close is not None]
            logger.info(f"  RSI 5m input (last 15 closes): {last_15_closes_5m}")
        
        # ATR input (last 15 candles from 5m)
        if len(self.candle_builder.candles_5m) > 0:
            last_15_5m = self.candle_builder.candles_5m[-15:]
            high_low_close = [(c.high, c.low, c.close) for c in last_15_5m if c.high and c.low and c.close]
            logger.info(f"  ATR 5m input (last 15 H/L/C): {high_low_close}")
        
        # 3. Live vs Engine price
        logger.info("\nPRICE COMPARISON:")
        ws_price = candle_status.get('current_price')
        
        if self.candle_builder.current_candle_1m and self.candle_builder.current_candle_1m.close:
            engine_price = self.candle_builder.current_candle_1m.close
            logger.info(f"  WebSocket Price: ${ws_price:.2f}" if ws_price else "  WebSocket Price: None")
            logger.info(f"  Latest 1m Candle Close: ${engine_price:.2f}")
            if ws_price:
                latency = abs(ws_price - engine_price)
                logger.info(f"  Difference: ${latency:.2f}")
        
        # 4. Candle counts
        logger.info("\nCANDLE COUNTS:")
        logger.info(f"  1m: {len(self.candle_builder.candles_1m)} completed + {1 if self.candle_builder.current_candle_1m else 0} building")
        logger.info(f"  5m: {len(self.candle_builder.candles_5m)}")
        logger.info(f"  15m: {len(self.candle_builder.candles_15m)}")
        
        # 5. Indicator values
        logger.info("\nINDICATOR VALUES:")
        logger.info(f"  EMA20 5m: {f'{ema20_5m:.2f}' if ema20_5m else 'None'}")
        logger.info(f"  EMA50 5m: {f'{ema50_5m:.2f}' if ema50_5m else 'None'}")
        logger.info(f"  ATR 5m: {f'{atr_5m:.2f}' if atr_5m else 'None'}")
        logger.info(f"  RSI 5m: {f'{rsi_5m:.2f}' if rsi_5m else 'None'}")
        
        logger.info("=" * 80)
    
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
            
            # Signal detection
            signals = self.signal_detector.detect_signal(
                regime,
                ema20_1m, ema50_1m,
                ema20_5m, ema50_5m,
                ema20_15m, ema50_15m,
                cvd_5m, obi,
                candle_status['current_price'],
                rsi_5m
            )
            
            # Check if we're approximating EMAs (insufficient data)
            approximating = {
                '1m': len(self.candle_builder.candles_1m) < 50,
                '5m': len(self.candle_builder.candles_5m) < 50,
                '15m': len(self.candle_builder.candles_15m) < 50
            }
            
            # Update state machine
            signal_status = self.state_machine.update(
                signals,
                candle_status['current_price'],
                atr_5m
            )
            
            # Send alerts if signal triggered
            if signal_status.get('signal_triggered'):
                self.alert_manager.send_signal_alert(
                    direction=signal_status['direction'],
                    confidence=signal_status['confidence'],
                    entry=signal_status['entry'],
                    stop_loss=signal_status['stop_loss'],
                    tp1=signal_status['tp1'],
                    tp2=signal_status['tp2'],
                    symbol=self.symbol
                )
            
            # Debug heartbeat log
            if self.debug:
                self._heartbeat_log(candle_status, ema20_5m, ema50_5m, atr_5m, rsi_5m)
            
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            ema20_1m = ema50_1m = ema20_5m = ema50_5m = ema20_15m = ema50_15m = None
            atr_5m = rsi_5m = obi = spread = depth = cvd_1m = cvd_5m = None
            regime = "RANGING"
            gates = {'spread': {'pass': False}, 'depth': {'pass': False}, 'all_pass': False}
            signals = {'short': {'checklist': {}, 'confidence': 0, 'signal_ready': False},
                      'long': {'checklist': {}, 'confidence': 0, 'signal_ready': False}}
            approximating = {'1m': True, '5m': True, '15m': True}
            signal_status = {'state': 'IDLE', 'direction': None, 'signal_triggered': False}
        
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
            },
            'regime': regime,
            'gates': gates,
            'signals': signals,
            'approximating': approximating,
            'signal_status': signal_status
        }
