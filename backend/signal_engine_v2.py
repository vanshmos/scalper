import asyncio
import logging
import time
from typing import Optional, Dict, List
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path

from okx_websocket import OKXWebSocketClient
from okx_rest import OKXRestClient
from candle_builder import Candle  # Use existing Candle class
from indicators import Indicators
from alerts import AlertManager
from rolling_stats import RollingStats
from signal_detector_alpha import SignalDetector, SignalDirection  # CRITICAL: Use institutional detector

logger = logging.getLogger(__name__)

def okx_to_candle(data: List) -> Candle:
    """Convert OKX candle format to Candle object"""
    # OKX format: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
    timestamp = int(data[0]) // 1000  # Convert ms to seconds
    candle = Candle(timestamp, '1m')  # Timeframe doesn't matter for data storage
    candle.open = float(data[1])
    candle.high = float(data[2])
    candle.low = float(data[3])
    candle.close = float(data[4])
    candle.volume = float(data[5])
    return candle

class SignalState:
    """Track active signal state"""
    def __init__(self):
        self.status = "IDLE"  # IDLE, FORMING, ACTIVE
        self.direction = None  # "LONG" or "SHORT"
        self.entry_price = None
        self.entry_time = None
        self.forming_start = None
        self.atr_at_entry = None
        
    def reset(self):
        self.status = "IDLE"
        self.direction = None
        self.entry_price = None
        self.entry_time = None
        self.forming_start = None
        self.atr_at_entry = None

class SignalEngine:
    """Multi-symbol signal engine using OKX candle channels"""
    
    def __init__(self, symbol: str, display_name: str):
        self.symbol = symbol  # e.g. "BTC-USDT-SWAP"
        self.display_name = display_name  # e.g. "BTC"
        self.rest_client = OKXRestClient()
        self.ws_client = OKXWebSocketClient(symbol)
        self.indicators = Indicators()
        self.alert_manager = AlertManager()
        
        # Regime detector
        from regime import RegimeDetector
        self.regime_detector = RegimeDetector()
        
        # CRITICAL: Initialize institutional-grade signal detector
        self.detector = SignalDetector()
        
        # Candle storage (using deque for efficient operations)
        self.candles_1m = deque(maxlen=200)  # Keep last 200 1m candles
        self.candles_5m = deque(maxlen=100)  # Keep last 100 5m candles
        self.candles_15m = deque(maxlen=50)  # Keep last 50 15m candles
        
        # Market data
        self.current_price = None
        self.mark_price = None
        self.funding_rate = None
        self.last_ticker = None
        self.last_orderbook = None
        self.taker_buy_ratio = 0.5  # Neutral default
        
        # Signal state
        self.signal_state = SignalState()
        
        # Warmup tracking
        self.is_warmed_up = False
        self.warmup_threshold = 50  # Require 50x 1m candles before signals
        
        # Cache file
        self.cache_file = Path("/app/data/candle_cache.json")
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Performance tracking
        self.recent_trades = deque(maxlen=50000)  # CRITICAL FIX: 50k trades = ~17min buffer for high volatility
        self.taker_buy_ratio_buffer = deque(maxlen=60)  # Separate buffer for quick buy/sell ratio
        
        # Statistical tracking for dynamic gates
        self.spread_stats = RollingStats(window_seconds=3600)  # 60 min rolling window
        self.depth_stats = RollingStats(window_seconds=3600)
        self.volume_stats = RollingStats(window_seconds=3600)
        
        # Staleness tracking
        self.last_ticker_time = None
        
        # EVENT-DRIVEN ARCHITECTURE: Throttle mechanism
        self.last_signal_check_time = 0
        self.signal_check_throttle = 0.1  # Check max every 100ms (10x faster than 1s polling)
        
    async def start(self):
        """Start the signal engine"""
        logger.info(f"Starting {self.display_name} signal engine for {self.symbol}...")
        
        # 1. Backfill historical data
        await self._backfill_candles()
        
        # 2. Fetch initial funding rate
        await self._fetch_funding_rate()
        
        # 3. Setup WebSocket callbacks
        self.ws_client.on_candle_1m = self._on_candle_1m
        self.ws_client.on_candle_5m = self._on_candle_5m
        self.ws_client.on_candle_15m = self._on_candle_15m  # Add 15m handler
        self.ws_client.on_ticker = self._on_ticker
        self.ws_client.on_orderbook = self._on_orderbook
        self.ws_client.on_trade = self._on_trade
        self.ws_client.on_funding_rate = self._on_funding_rate
        self.ws_client.on_mark_price = self._on_mark_price
        
        # 4. Start WebSocket connection
        asyncio.create_task(self.ws_client.start())
        
        # 5. Start signal processing loop
        asyncio.create_task(self._signal_processing_loop())
        
        logger.info(f"{self.display_name} signal engine started successfully")
    
    async def _backfill_candles(self):
        """Backfill historical candles from REST API"""
        try:
            logger.info("Backfilling historical candles...")
            
            # Fetch 1m candles
            candles_1m_data = self.rest_client.get_candles(self.symbol, "1m", 100)
            if candles_1m_data:
                # OKX returns newest first, reverse to get chronological order
                for candle_data in reversed(candles_1m_data):
                    candle = okx_to_candle(candle_data)
                    self.candles_1m.append(candle)
                logger.info(f"Backfilled {len(candles_1m_data)} 1m candles")
            
            # Fetch 5m candles
            candles_5m_data = self.rest_client.get_candles(self.symbol, "5m", 50)
            if candles_5m_data:
                for candle_data in reversed(candles_5m_data):
                    candle = okx_to_candle(candle_data)
                    candle.timeframe = '5m'
                    self.candles_5m.append(candle)
                logger.info(f"Backfilled {len(candles_5m_data)} 5m candles")
            
            # Fetch 15m candles
            candles_15m_data = self.rest_client.get_candles(self.symbol, "15m", 30)
            if candles_15m_data:
                for candle_data in reversed(candles_15m_data):
                    candle = okx_to_candle(candle_data)
                    candle.timeframe = '15m'
                    self.candles_15m.append(candle)
                logger.info(f"Backfilled {len(candles_15m_data)} 15m candles")
            
            # Check warmup status
            if len(self.candles_1m) >= self.warmup_threshold:
                self.is_warmed_up = True
                logger.info(f"✓ Warmup complete: {len(self.candles_1m)} 1m candles available")
            else:
                logger.warning(f"Warmup incomplete: {len(self.candles_1m)}/{self.warmup_threshold} candles")
                
        except Exception as e:
            logger.error(f"Error during backfill: {e}")
    
    async def _fetch_funding_rate(self):
        """Fetch current funding rate"""
        try:
            funding_data = self.rest_client.get_funding_rate(self.symbol)
            if funding_data:
                self.funding_rate = float(funding_data.get('fundingRate', 0))
                logger.info(f"Current funding rate: {self.funding_rate:.4%}")
        except Exception as e:
            logger.error(f"Error fetching funding rate: {e}")
    
    async def _on_candle_1m(self, data: dict):
        """Handle 1m candle updates"""
        try:
            candle = okx_to_candle(data)
            confirm = data[8] if len(data) > 8 else '0'
            
            # Only add confirmed candles to avoid duplicates
            if confirm == '1':
                # Check if this candle already exists (by timestamp)
                if not self.candles_1m or self.candles_1m[-1].timestamp != candle.timestamp:
                    self.candles_1m.append(candle)
                    logger.debug(f"Added confirmed 1m candle: {candle.timestamp}")
                    
                    # Update warmup status
                    if not self.is_warmed_up and len(self.candles_1m) >= self.warmup_threshold:
                        self.is_warmed_up = True
                        logger.info(f"✓ Warmup complete: {len(self.candles_1m)} 1m candles")
            
            # Always update current price from latest candle
            self.current_price = candle.close
            
        except Exception as e:
            logger.error(f"Error handling 1m candle: {e}")
    
    async def _on_candle_5m(self, data: dict):
        """Handle 5m candle updates"""
        try:
            candle = okx_to_candle(data)
            candle.timeframe = '5m'
            confirm = data[8] if len(data) > 8 else '0'
            
            # Only add confirmed candles
            if confirm == '1':
                if not self.candles_5m or self.candles_5m[-1].timestamp != candle.timestamp:
                    self.candles_5m.append(candle)
                    logger.debug(f"Added confirmed 5m candle: {candle.timestamp}")
                    
        except Exception as e:
            logger.error(f"Error handling 5m candle: {e}")
    
    async def _on_candle_15m(self, data: dict):
        """Handle 15m candle updates"""
        try:
            candle = okx_to_candle(data)
            candle.timeframe = '15m'
            confirm = data[8] if len(data) > 8 else '0'
            
            # Only add confirmed candles
            if confirm == '1':
                if not self.candles_15m or self.candles_15m[-1].timestamp != candle.timestamp:
                    self.candles_15m.append(candle)
                    logger.debug(f"Added confirmed 15m candle: {candle.timestamp}")
                    
        except Exception as e:
            logger.error(f"Error handling 15m candle: {e}")
    
    async def _on_ticker(self, data: dict):
        """Handle ticker updates"""
        try:
            self.last_ticker = data
            self.last_ticker_time = time.time()  # Track ticker freshness
            if 'last' in data:
                self.current_price = float(data['last'])
        except Exception as e:
            logger.error(f"Error handling ticker: {e}")
    
    async def _on_orderbook(self, data: dict):
        """Handle orderbook updates - EVENT-DRIVEN signal check"""
        try:
            self.last_orderbook = data
            
            # Feed spread and depth to rolling stats
            if self.last_orderbook:
                spread = self.indicators.calculate_spread(self.last_orderbook)
                depth = self.indicators.calculate_depth(self.last_orderbook)
                
                if spread is not None:
                    self.spread_stats.add(spread)
                if depth is not None:
                    self.depth_stats.add(depth)
            
            # EVENT-DRIVEN: Trigger signal check on orderbook update
            await self._check_signals_event_driven()
                    
        except Exception as e:
            logger.error(f"Error handling orderbook: {e}")
    
    async def _on_trade(self, data: dict):
        """Handle trade updates - track for CVD and taker buy/sell ratio + EVENT-DRIVEN check"""
        try:
            # OKX trade format: {side: 'buy'/'sell', sz: size, px: price, ts: timestamp}
            side = data.get('side')
            size = float(data.get('sz', 0))
            timestamp = int(data.get('ts', 0))  # Keep in milliseconds for indicators.py
            
            # Store trade in format expected by indicators.calculate_cvd()
            trade = {
                'side': side,
                'sz': size,  # indicators.py expects 'sz' key
                'ts': timestamp  # indicators.py expects 'ts' key in milliseconds
            }
            
            # Add to recent trades for CVD calculation
            self.recent_trades.append(trade)
            
            # Also track for quick taker buy ratio (last 60 trades)
            self.taker_buy_ratio_buffer.append({
                'side': side,
                'size': size
            })
            
            # Calculate taker buy ratio (for display/quick checks)
            if len(self.taker_buy_ratio_buffer) > 10:
                buy_volume = sum(t['size'] for t in self.taker_buy_ratio_buffer if t['side'] == 'buy')
                total_volume = sum(t['size'] for t in self.taker_buy_ratio_buffer)
                self.taker_buy_ratio = buy_volume / total_volume if total_volume > 0 else 0.5
            
            # EVENT-DRIVEN: Trigger signal check on trade (throttled to 100ms)
            await self._check_signals_event_driven()
                
        except Exception as e:
            logger.error(f"Error handling trade: {e}")
    
    async def _on_funding_rate(self, data: dict):
        """Handle funding rate updates"""
        try:
            if 'fundingRate' in data:
                self.funding_rate = float(data['fundingRate'])
                logger.debug(f"Funding rate updated: {self.funding_rate:.4%}")
        except Exception as e:
            logger.error(f"Error handling funding rate: {e}")
    
    async def _on_mark_price(self, data: dict):
        """Handle mark price updates"""
        try:
            if 'markPx' in data:
                self.mark_price = float(data['markPx'])
        except Exception as e:
            logger.error(f"Error handling mark price: {e}")
    
    async def _signal_processing_loop(self):
        """
        DEPRECATED POLLING LOOP - Kept for graceful shutdown only
        Real signal processing now happens via event-driven callbacks
        """
        while True:
            try:
                await asyncio.sleep(10)  # Just keep alive, real work done in callbacks
            except Exception as e:
                logger.error(f"Error in keepalive loop: {e}")
    
    async def _check_signals_event_driven(self):
        """
        EVENT-DRIVEN signal check - called from orderbook/trade callbacks
        Implements 100ms throttle to prevent CPU overload
        REFACTORED: Delegates to institutional SignalDetector
        """
        try:
            current_time = time.time()
            
            # Throttle: only check every 100ms
            if current_time - self.last_signal_check_time < self.signal_check_throttle:
                return
            
            self.last_signal_check_time = current_time
            
            # STRICT WARMUP: Block all signals until sufficient data
            if len(self.candles_5m) < 50:
                return
            
            # STALENESS CIRCUIT BREAKER: Block signals if ticker data is stale
            if self.last_ticker_time is None:
                return
            
            ticker_age_ms = (current_time - self.last_ticker_time) * 1000
            if ticker_age_ms > 2000:  # 2 seconds
                return
            
            # Calculate indicators with LIVE data (forming candles)
            indicators = self._calculate_indicators_live()
            
            # Detect regime
            candles_5m_list = list(self.candles_5m)
            regime = self.regime_detector.detect_regime(
                candles_5m_list,
                indicators.get('ema20_5m'),
                indicators.get('ema50_5m'),
                indicators.get('rsi'),
                indicators.get('cvd', {}).get('5m')
            )
            
            # CRITICAL: Use institutional SignalDetector for LONG signals
            long_result = self.detector.detect_signal_with_alpha(
                direction=SignalDirection.LONG,
                regime=regime,
                ema20_1m=indicators.get('ema20_1m'),
                ema50_1m=indicators.get('ema50_1m'),
                ema20_5m=indicators.get('ema20_5m'),
                ema50_5m=indicators.get('ema50_5m'),
                ema20_15m=indicators.get('ema20_15m'),
                ema50_15m=indicators.get('ema50_15m'),
                cvd_5m=indicators.get('cvd', {}).get('5m'),
                obi=indicators.get('obi'),
                current_price=indicators.get('price'),
                rsi_5m=indicators.get('rsi'),
                spread=indicators.get('spread'),
                atr=indicators.get('atr'),
                # ALPHA inputs
                obi_velocity=indicators.get('obi_velocity'),
                cvd_velocity=indicators.get('cvd_velocity'),
                bollinger=indicators.get('bollinger'),
                vwap=indicators.get('vwap'),
                trend_strength=indicators.get('trend_strength'),
                hurst=None  # Using trend_strength instead
            )
            
            # CRITICAL: Use institutional SignalDetector for SHORT signals
            short_result = self.detector.detect_signal_with_alpha(
                direction=SignalDirection.SHORT,
                regime=regime,
                ema20_1m=indicators.get('ema20_1m'),
                ema50_1m=indicators.get('ema50_1m'),
                ema20_5m=indicators.get('ema20_5m'),
                ema50_5m=indicators.get('ema50_5m'),
                ema20_15m=indicators.get('ema20_15m'),
                ema50_15m=indicators.get('ema50_15m'),
                cvd_5m=indicators.get('cvd', {}).get('5m'),
                obi=indicators.get('obi'),
                current_price=indicators.get('price'),
                rsi_5m=indicators.get('rsi'),
                spread=indicators.get('spread'),
                atr=indicators.get('atr'),
                # ALPHA inputs
                obi_velocity=indicators.get('obi_velocity'),
                cvd_velocity=indicators.get('cvd_velocity'),
                bollinger=indicators.get('bollinger'),
                vwap=indicators.get('vwap'),
                trend_strength=indicators.get('trend_strength'),
                hurst=None
            )
            
            # Determine which signal is stronger
            if long_result['signal_ready'] and short_result['signal_ready']:
                # Both ready, choose higher score
                if long_result['score'] >= short_result['score']:
                    active_result = long_result
                    active_direction = 'LONG'
                else:
                    active_result = short_result
                    active_direction = 'SHORT'
            elif long_result['signal_ready']:
                active_result = long_result
                active_direction = 'LONG'
            elif short_result['signal_ready']:
                active_result = short_result
                active_direction = 'SHORT'
            else:
                active_result = None
                active_direction = None
            
            # Process signal state machine
            await self._process_signal_state_with_detector(
                active_result, 
                active_direction, 
                indicators,
                long_result,
                short_result
            )
            
        except Exception as e:
            logger.error(f"Error in event-driven signal check: {e}")
    
    def _calculate_indicators_live(self) -> Dict:
        """
        Calculate indicators with LIVE data (including forming candles)
        INSTITUTIONAL UPGRADE: Synthesizes forming 5m and 15m candles to eliminate trend latency
        """
        try:
            # Get candle lists
            candles_1m_list = list(self.candles_1m)
            candles_5m_list = list(self.candles_5m)
            candles_15m_list = list(self.candles_15m)
            
            # LIVE INDICATORS: Inject forming candle if current price available
            # This gives real-time EMA/RSI instead of stale data
            if self.current_price and len(candles_1m_list) > 0:
                # Create forming 1m candle from current market state
                last_confirmed_1m = candles_1m_list[-1]
                current_timestamp = int(time.time())
                
                forming_candle_1m = Candle(current_timestamp, '1m')
                forming_candle_1m.open = last_confirmed_1m.close
                forming_candle_1m.high = max(last_confirmed_1m.close, self.current_price)
                forming_candle_1m.low = min(last_confirmed_1m.close, self.current_price)
                forming_candle_1m.close = self.current_price
                forming_candle_1m.volume = 0
                
                candles_1m_live = candles_1m_list + [forming_candle_1m]
            else:
                candles_1m_live = candles_1m_list
            
            # INSTITUTIONAL UPGRADE: Synthesize forming 5m and 15m candles
            # This eliminates 5-minute trend detection latency
            if self.current_price and len(candles_5m_list) > 0:
                last_confirmed_5m = candles_5m_list[-1]
                
                # Aggregate recent 1m candles since last 5m close
                # Get 1m candles after the last 5m candle timestamp
                recent_1m = [c for c in candles_1m_list if c.timestamp > last_confirmed_5m.timestamp]
                
                forming_candle_5m = Candle(int(time.time()), '5m')
                forming_candle_5m.open = last_confirmed_5m.close
                
                # Aggregate high/low/volume from recent 1m candles + current price
                if recent_1m:
                    highs = [c.high for c in recent_1m if c.high] + [self.current_price]
                    lows = [c.low for c in recent_1m if c.low] + [self.current_price]
                    forming_candle_5m.high = max(highs)
                    forming_candle_5m.low = min(lows)
                    forming_candle_5m.volume = sum(c.volume for c in recent_1m if c.volume)
                else:
                    forming_candle_5m.high = max(last_confirmed_5m.close, self.current_price)
                    forming_candle_5m.low = min(last_confirmed_5m.close, self.current_price)
                    forming_candle_5m.volume = 0
                
                forming_candle_5m.close = self.current_price
                
                candles_5m_live = candles_5m_list + [forming_candle_5m]
            else:
                candles_5m_live = candles_5m_list
            
            # Synthesize forming 15m candle
            if self.current_price and len(candles_15m_list) > 0:
                last_confirmed_15m = candles_15m_list[-1]
                
                # Aggregate recent 5m candles since last 15m close
                recent_5m = [c for c in candles_5m_list if c.timestamp > last_confirmed_15m.timestamp]
                
                forming_candle_15m = Candle(int(time.time()), '15m')
                forming_candle_15m.open = last_confirmed_15m.close
                
                if recent_5m:
                    highs = [c.high for c in recent_5m if c.high] + [self.current_price]
                    lows = [c.low for c in recent_5m if c.low] + [self.current_price]
                    forming_candle_15m.high = max(highs)
                    forming_candle_15m.low = min(lows)
                    forming_candle_15m.volume = sum(c.volume for c in recent_5m if c.volume)
                else:
                    forming_candle_15m.high = max(last_confirmed_15m.close, self.current_price)
                    forming_candle_15m.low = min(last_confirmed_15m.close, self.current_price)
                    forming_candle_15m.volume = 0
                
                forming_candle_15m.close = self.current_price
                
                candles_15m_live = candles_15m_list + [forming_candle_15m]
            else:
                candles_15m_live = candles_15m_list
            
            # EMAs on 1m (LIVE)
            ema20_1m = self.indicators.calculate_ema(candles_1m_live, 20)
            ema50_1m = self.indicators.calculate_ema(candles_1m_live, 50)
            
            # EMAs on 5m (LIVE - now updates every second, not every 5 minutes!)
            ema20_5m = self.indicators.calculate_ema(candles_5m_live, 20)
            ema50_5m = self.indicators.calculate_ema(candles_5m_live, 50)
            
            # EMAs on 15m (LIVE - now updates every second, not every 15 minutes!)
            ema20_15m = self.indicators.calculate_ema(candles_15m_live, 20)
            ema50_15m = self.indicators.calculate_ema(candles_15m_live, 50)
            
            # ATR on 5m (use live for better responsiveness)
            atr = self.indicators.calculate_atr(candles_5m_live, 14)
            
            # RSI on 5m (use live for faster momentum detection)
            rsi = self.indicators.calculate_rsi(candles_5m_live, 14)
            
            # Orderbook indicators (already real-time with books50)
            obi = None
            spread = None
            depth = None
            if self.last_orderbook:
                obi = self.indicators.calculate_obi(self.last_orderbook)  # Weighted OBI with 50 levels
                spread = self.indicators.calculate_spread(self.last_orderbook)
                depth = self.indicators.calculate_depth(self.last_orderbook)  # 50 levels
            
            # CRITICAL: Calculate CVD explicitly to populate cvd_history for velocity
            trades_list = list(self.recent_trades)
            
            cvd_1m = self.indicators.calculate_cvd(trades_list, window_seconds=60)
            cvd_5m = self.indicators.calculate_cvd(trades_list, window_seconds=300)
            
            # ALPHA ENHANCEMENTS
            obi_velocity = self.indicators.get_obi_velocity()
            cvd_velocity = self.indicators.get_cvd_velocity()
            
            bollinger = self.indicators.calculate_bollinger_bands(candles_5m_live, period=20, std_dev=2.0)
            vwap = self.indicators.calculate_vwap(candles_5m_live)
            trend_strength = self.indicators.calculate_trend_strength(candles_5m_live, period=20)
            
            price_for_distance = self.mark_price if self.mark_price else self.current_price
            
            return {
                'ema20_1m': ema20_1m,
                'ema50_1m': ema50_1m,
                'ema20_5m': ema20_5m,
                'ema50_5m': ema50_5m,
                'ema20_15m': ema20_15m,
                'ema50_15m': ema50_15m,
                'atr': atr if atr and atr > 0 else 100,
                'rsi': rsi,
                'obi': obi,
                'spread': spread,
                'depth': depth,
                'price': price_for_distance,
                'taker_buy_ratio': self.taker_buy_ratio,
                'cvd': {
                    '1m': cvd_1m,
                    '5m': cvd_5m
                },
                'obi_velocity': obi_velocity,
                'cvd_velocity': cvd_velocity,
                'bollinger': bollinger,
                'vwap': vwap,
                'trend_strength': trend_strength
            }
            
        except Exception as e:
            logger.error(f"Error calculating live indicators: {e}")
            return {}
        """
        Calculate indicators with LIVE data (including forming candles)
        This eliminates 1-minute lag by using current market state
        """
        try:
            # Get candle lists
            candles_1m_list = list(self.candles_1m)
            candles_5m_list = list(self.candles_5m)
            candles_15m_list = list(self.candles_15m)
            
            # LIVE INDICATORS: Inject forming candle if current price available
            # This gives real-time EMA/RSI instead of 1-minute stale data
            if self.current_price and len(candles_1m_list) > 0:
                # Create forming candle from current market state
                last_confirmed = candles_1m_list[-1]
                current_timestamp = int(time.time())
                
                forming_candle = Candle(current_timestamp, '1m')
                forming_candle.open = last_confirmed.close  # Assume opens at last close
                forming_candle.high = max(last_confirmed.close, self.current_price)
                forming_candle.low = min(last_confirmed.close, self.current_price)
                forming_candle.close = self.current_price
                forming_candle.volume = 0  # Don't have forming volume yet
                
                # Prepend forming candle to lists for calculation
                candles_1m_live = candles_1m_list + [forming_candle]
            else:
                candles_1m_live = candles_1m_list
            
            # EMAs on 1m (LIVE)
            ema20_1m = self.indicators.calculate_ema(candles_1m_live, 20)
            ema50_1m = self.indicators.calculate_ema(candles_1m_live, 50)
            
            # EMAs on 5m (confirmed only - less critical for 5m lag)
            ema20_5m = self.indicators.calculate_ema(candles_5m_list, 20)
            ema50_5m = self.indicators.calculate_ema(candles_5m_list, 50)
            
            # EMAs on 15m
            ema20_15m = self.indicators.calculate_ema(candles_15m_list, 20)
            ema50_15m = self.indicators.calculate_ema(candles_15m_list, 50)
            
            # ATR on 5m
            atr = self.indicators.calculate_atr(candles_5m_list, 14)
            
            # RSI on 5m (could use live 1m for faster response)
            rsi = self.indicators.calculate_rsi(candles_5m_list, 14)
            
            # Orderbook indicators (already real-time)
            obi = None
            spread = None
            depth = None
            if self.last_orderbook:
                obi = self.indicators.calculate_obi(self.last_orderbook)
                spread = self.indicators.calculate_spread(self.last_orderbook)
                depth = self.indicators.calculate_depth(self.last_orderbook)
            
            # CRITICAL: Calculate CVD explicitly to populate cvd_history for velocity
            # Convert deque to list once
            trades_list = list(self.recent_trades)
            
            # Calculate CVDs (This side-effect populates self.indicators.cvd_history)
            cvd_1m = self.indicators.calculate_cvd(trades_list, window_seconds=60)
            cvd_5m = self.indicators.calculate_cvd(trades_list, window_seconds=300)
            
            # ALPHA ENHANCEMENTS: New indicators
            
            # 1. Velocity signals (anti-spoofing) - NOW PROPERLY POPULATED
            obi_velocity = self.indicators.get_obi_velocity()
            cvd_velocity = self.indicators.get_cvd_velocity()
            
            # 2. Bollinger Bands (liquidity sweep detection)
            bollinger = self.indicators.calculate_bollinger_bands(candles_5m_list, period=20, std_dev=2.0)
            
            # 3. VWAP (slippage protection)
            vwap = self.indicators.calculate_vwap(candles_5m_list)
            
            # 4. Trend Strength (adaptive targets)
            trend_strength = self.indicators.calculate_trend_strength(candles_5m_list, period=20)
            
            # Use mark price for distance calculation (more stable)
            price_for_distance = self.mark_price if self.mark_price else self.current_price
            
            return {
                'ema20_1m': ema20_1m,
                'ema50_1m': ema50_1m,
                'ema20_5m': ema20_5m,
                'ema50_5m': ema50_5m,
                'ema20_15m': ema20_15m,
                'ema50_15m': ema50_15m,
                'atr': atr if atr and atr > 0 else 100,  # Default to 100 if ATR is 0
                'rsi': rsi,
                'obi': obi,
                'spread': spread,
                'depth': depth,
                'price': price_for_distance,
                'taker_buy_ratio': self.taker_buy_ratio,
                # CVD values (calculated from trades)
                'cvd': {
                    '1m': cvd_1m,
                    '5m': cvd_5m
                },
                # ALPHA indicators
                'obi_velocity': obi_velocity,
                'cvd_velocity': cvd_velocity,
                'bollinger': bollinger,
                'vwap': vwap,
                'trend_strength': trend_strength
            }
            
        except Exception as e:
            logger.error(f"Error calculating live indicators: {e}")
            return {}
    
    def _calculate_indicators(self) -> Dict:
        """
        LEGACY: Calculate indicators (kept for get_status compatibility)
        Use _calculate_indicators_live() for signal processing
        """
        return self._calculate_indicators_live()
        """Calculate all indicators including ALPHA enhancements"""
        try:
            # Get candle lists
            candles_1m_list = list(self.candles_1m)
            candles_5m_list = list(self.candles_5m)
            candles_15m_list = list(self.candles_15m)
            
            # EMAs on 1m
            ema20_1m = self.indicators.calculate_ema(candles_1m_list, 20)
            ema50_1m = self.indicators.calculate_ema(candles_1m_list, 50)
            
            # EMAs on 5m
            ema20_5m = self.indicators.calculate_ema(candles_5m_list, 20)
            ema50_5m = self.indicators.calculate_ema(candles_5m_list, 50)
            
            # EMAs on 15m
            ema20_15m = self.indicators.calculate_ema(candles_15m_list, 20)
            ema50_15m = self.indicators.calculate_ema(candles_15m_list, 50)
            
            # ATR on 5m
            atr = self.indicators.calculate_atr(candles_5m_list, 14)
            
            # RSI on 5m
            rsi = self.indicators.calculate_rsi(candles_5m_list, 14)
            
            # Orderbook indicators
            obi = None
            spread = None
            depth = None
            if self.last_orderbook:
                obi = self.indicators.calculate_obi(self.last_orderbook)
                spread = self.indicators.calculate_spread(self.last_orderbook)
                depth = self.indicators.calculate_depth(self.last_orderbook)
            
            # CRITICAL: Calculate CVD explicitly to populate cvd_history for velocity
            # Convert deque to list once
            trades_list = list(self.recent_trades)
            
            # Calculate CVDs (This side-effect populates self.indicators.cvd_history)
            cvd_1m = self.indicators.calculate_cvd(trades_list, window_seconds=60)
            cvd_5m = self.indicators.calculate_cvd(trades_list, window_seconds=300)
            
            # ALPHA ENHANCEMENTS: New indicators
            
            # 1. Velocity signals (anti-spoofing) - NOW PROPERLY POPULATED
            obi_velocity = self.indicators.get_obi_velocity()
            cvd_velocity = self.indicators.get_cvd_velocity()
            
            # 2. Bollinger Bands (liquidity sweep detection)
            bollinger = self.indicators.calculate_bollinger_bands(candles_5m_list, period=20, std_dev=2.0)
            
            # 3. VWAP (slippage protection)
            vwap = self.indicators.calculate_vwap(candles_5m_list)
            
            # 4. Trend Strength (adaptive targets)
            trend_strength = self.indicators.calculate_trend_strength(candles_5m_list, period=20)
            
            # Use mark price for distance calculation (more stable)
            price_for_distance = self.mark_price if self.mark_price else self.current_price
            
            return {
                'ema20_1m': ema20_1m,
                'ema50_1m': ema50_1m,
                'ema20_5m': ema20_5m,
                'ema50_5m': ema50_5m,
                'ema20_15m': ema20_15m,
                'ema50_15m': ema50_15m,
                'atr': atr if atr and atr > 0 else 100,  # Default to 100 if ATR is 0
                'rsi': rsi,
                'obi': obi,
                'spread': spread,
                'depth': depth,
                'price': price_for_distance,
                'taker_buy_ratio': self.taker_buy_ratio,
                # CVD values (calculated from trades)
                'cvd': {
                    '1m': cvd_1m,
                    '5m': cvd_5m
                },
                # ALPHA indicators
                'obi_velocity': obi_velocity,
                'cvd_velocity': cvd_velocity,
                'bollinger': bollinger,
                'vwap': vwap,
                'trend_strength': trend_strength
            }
            
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            return {}
    
    def _build_checklist(self, indicators: Dict) -> Dict:
        """Build signal checklist with PRO SCALPER quality filters"""
        try:
            checklist = {
                'regime': False,
                'trend_align': False,
                'cvd': False,
                'obi': False,
                'ema_dist': False,
                'funding': False,
                'gates': False,
                'volume_surge': False,        # NEW: Volume confirmation
                'clean_breakout': False,      # NEW: No choppy wicks
                'atr_expansion': False,       # NEW: Volatility increasing
                'rsi_momentum': False,        # NEW: RSI moving with trend
                'ema_quality': False,         # NEW: EMAs spreading not converging
                'time_filter': False          # NEW: Avoid dead hours
            }
            
            # Get values
            ema20_1m = indicators.get('ema20_1m')
            ema50_1m = indicators.get('ema50_1m')
            ema20_5m = indicators.get('ema20_5m')
            ema50_5m = indicators.get('ema50_5m')
            price = indicators.get('price')
            obi = indicators.get('obi')
            spread = indicators.get('spread')
            depth = indicators.get('depth')
            rsi = indicators.get('rsi')
            atr = indicators.get('atr')
            
            # 1. Regime (5m trend + price confirmation + volume validation)
            if ema20_5m and ema50_5m and price:
                # Calculate EMA separation percentage
                ema_diff_pct = abs(ema20_5m - ema50_5m) / ema50_5m * 100
                
                # Check if we have volume data for confidence
                volume_confirms = False
                if len(self.candles_5m) >= 3:
                    recent_vols = [c.volume for c in list(self.candles_5m)[-3:]]
                    avg_recent_vol = sum(recent_vols) / len(recent_vols)
                    # Volume should be above 50% of recent average (not dead)
                    if len(self.candles_5m) >= 10:
                        older_vols = [c.volume for c in list(self.candles_5m)[-10:-3]]
                        avg_older_vol = sum(older_vols) / len(older_vols) if older_vols else avg_recent_vol
                        volume_confirms = avg_recent_vol > avg_older_vol * 0.5
                    else:
                        volume_confirms = True
                
                # Primary check: EMA crossover (require >0.1% separation to avoid noise)
                # FIXED: Increased from 0.05% to 0.1% for cleaner signals
                if ema_diff_pct > 0.1 and volume_confirms:
                    is_bull_5m = ema20_5m > ema50_5m
                    is_bear_5m = ema20_5m < ema50_5m
                else:
                    # EMAs too close or volume too low = RANGING
                    is_bull_5m = False
                    is_bear_5m = False
                
                # Secondary check: Price position (catches fast moves)
                avg_ema = (ema20_5m + ema50_5m) / 2
                price_pct_diff = ((price - avg_ema) / avg_ema) * 100
                
                # FIXED: Tightened from 1% to 1.5% to avoid false breakouts
                if price_pct_diff > 1.5 and volume_confirms:
                    is_bull_5m = True
                    is_bear_5m = False
                elif price_pct_diff < -1.5 and volume_confirms:
                    is_bull_5m = False
                    is_bear_5m = True
                
                checklist['regime'] = is_bull_5m or is_bear_5m
                checklist['regime_direction'] = 'BULL' if is_bull_5m else 'BEAR' if is_bear_5m else 'RANGING'
                checklist['ema_separation_pct'] = ema_diff_pct
            
            # 2. Multi-TF alignment (1m AND 5m must agree)
            if ema20_1m and ema50_1m and ema20_5m and ema50_5m:
                trend_1m = 'BULL' if ema20_1m > ema50_1m else 'BEAR'
                trend_5m = 'BULL' if ema20_5m > ema50_5m else 'BEAR'
                checklist['trend_align'] = trend_1m == trend_5m
                checklist['trend_direction'] = trend_1m if checklist['trend_align'] else 'DIVERGENT'
            
            # 3. CVD (using taker buy ratio as proxy)
            # FIXED: Loosened from 0.60/0.40 to 0.55/0.45 (more realistic)
            if checklist.get('regime_direction') == 'BULL':
                checklist['cvd'] = self.taker_buy_ratio > 0.55
            elif checklist.get('regime_direction') == 'BEAR':
                checklist['cvd'] = self.taker_buy_ratio < 0.45
            
            # 4. OBI - FIXED: Loosened from 0.20 to 0.15 (more realistic)
            if obi is not None:
                if checklist.get('regime_direction') == 'BULL':
                    checklist['obi'] = obi > 0.15
                elif checklist.get('regime_direction') == 'BEAR':
                    checklist['obi'] = obi < -0.15
            
            # 5. EMA distance (keep 0.5%)
            if price and ema20_5m:
                distance_pct = abs(price - ema20_5m) / ema20_5m * 100
                checklist['ema_dist'] = distance_pct < 0.5
                checklist['ema_dist_value'] = distance_pct
            
            # 6. Funding filter (tighter: block when |funding| > 0.02% not 0.03%)
            if self.funding_rate is not None:
                abs_funding = abs(self.funding_rate)
                checklist['funding'] = abs_funding < 0.0002  # 0.02% = 0.0002
                checklist['funding_value'] = self.funding_rate
            
            # 7. Gates - DYNAMIC THRESHOLDS using statistical analysis
            gates_pass = True
            
            # Dynamic spread gate: Must be < (Mean + 2.5 * StDev) - loosened for crypto volatility
            if spread is not None:
                spread_threshold_dynamic = self.spread_stats.get_threshold(mode='upper', std_multiplier=2.5)
                if spread_threshold_dynamic is not None:
                    # Use dynamic threshold (but cap at 3.0 bps for safety)
                    effective_threshold = min(spread_threshold_dynamic, 3.0)
                    gates_pass = gates_pass and spread < effective_threshold
                    checklist['spread_threshold'] = effective_threshold
                else:
                    # Fallback to static threshold during warmup
                    gates_pass = gates_pass and spread < 2.0
                    checklist['spread_threshold'] = 2.0
            
            # Dynamic depth gate: Must be > (Mean - 2.0 * StDev) - very loose for crypto volatility
            if depth is not None:
                depth_threshold_dynamic = self.depth_stats.get_threshold(mode='lower', std_multiplier=2.0)
                if depth_threshold_dynamic is not None:
                    # Use dynamic threshold (but floor at $100k minimum)
                    effective_threshold = max(depth_threshold_dynamic, 100000)
                    gates_pass = gates_pass and depth > effective_threshold
                    checklist['depth_threshold'] = effective_threshold
                else:
                    # Fallback to static threshold during warmup
                    gates_pass = gates_pass and depth > 200000
                    checklist['depth_threshold'] = 200000
            
            checklist['gates'] = gates_pass
            checklist['spread_value'] = spread
            checklist['depth_value'] = depth
            
            # === PRO SCALPER FILTERS ===
            
            # 8. Volume surge - check if current volume trending up
            if len(self.candles_5m) >= 6:
                recent_volumes = [c.volume for c in list(self.candles_5m)[-6:]]
                current_vol = recent_volumes[-1]
                avg_last_5 = sum(recent_volumes[-6:-1]) / 5
                checklist['volume_surge'] = current_vol > avg_last_5 * 1.3
                checklist['volume_ratio'] = current_vol / avg_last_5 if avg_last_5 > 0 else 0
            
            # 9. Clean breakout - check last 3 candles for clean move (no big wicks against trend)
            if len(self.candles_5m) >= 3:
                last_3 = list(self.candles_5m)[-3:]
                clean = True
                for candle in last_3:
                    body_size = abs(candle.close - candle.open)
                    total_range = candle.high - candle.low
                    if total_range > 0:
                        body_pct = body_size / total_range
                        # Require at least 50% of candle is body (not wick)
                        if body_pct < 0.5:
                            clean = False
                            break
                checklist['clean_breakout'] = clean
            
            # 10. ATR expansion - volatility should be increasing, not dying
            if len(self.candles_5m) >= 20:
                current_atr = atr
                # Calculate ATR from 10 candles ago
                old_candles = list(self.candles_5m)[-20:-10]
                old_atr = self.indicators.calculate_atr(old_candles, 14)
                if old_atr and current_atr:
                    checklist['atr_expansion'] = current_atr > old_atr * 1.1  # 10% increase
                    checklist['atr_change_pct'] = ((current_atr - old_atr) / old_atr * 100) if old_atr > 0 else 0
            
            # 11. RSI momentum - RSI should be moving in signal direction
            if len(self.candles_5m) >= 3 and rsi:
                prev_candles = list(self.candles_5m)[-3:-1]
                prev_rsi = self.indicators.calculate_rsi(prev_candles, 14)
                if prev_rsi:
                    rsi_change = rsi - prev_rsi
                    if checklist.get('regime_direction') == 'BULL':
                        checklist['rsi_momentum'] = rsi_change > 0  # RSI rising
                    elif checklist.get('regime_direction') == 'BEAR':
                        checklist['rsi_momentum'] = rsi_change < 0  # RSI falling
                    checklist['rsi_change'] = rsi_change
            
            # 12. EMA quality - EMAs should be spreading, not converging
            if ema20_5m and ema50_5m and len(self.candles_5m) >= 3:
                current_spread = abs(ema20_5m - ema50_5m)
                # Calculate EMA spread 2 candles ago
                old_candles = list(self.candles_5m)[:-2]
                old_ema20 = self.indicators.calculate_ema(old_candles, 20)
                old_ema50 = self.indicators.calculate_ema(old_candles, 50)
                if old_ema20 and old_ema50:
                    old_spread = abs(old_ema20 - old_ema50)
                    checklist['ema_quality'] = current_spread > old_spread  # Spreading
            
            # 13. Time filter - avoid dead hours (2-6am ET, 11:30am-12:30pm ET)
            from datetime import datetime, timezone
            import pytz
            et_tz = pytz.timezone('America/New_York')
            current_et = datetime.now(timezone.utc).astimezone(et_tz)
            hour = current_et.hour
            minute = current_et.minute
            
            # Block: 2am-6am ET (Asian dead hours) and 11:30am-12:30pm ET (lunch)
            if 2 <= hour < 6:
                checklist['time_filter'] = False
            elif hour == 11 and minute >= 30:
                checklist['time_filter'] = False
            elif hour == 12 and minute < 30:
                checklist['time_filter'] = False
            else:
                checklist['time_filter'] = True
            
            return checklist
            
        except Exception as e:
            logger.error(f"Error building checklist: {e}")
            return {}
    
    async def _process_signal_state_with_detector(
        self, 
        active_result: Optional[Dict], 
        active_direction: Optional[str],
        indicators: Dict,
        long_result: Dict,
        short_result: Dict
    ):
        """
        Process signal state machine using SignalDetector results
        REFACTORED: Works with institutional detector output
        """
        try:
            current_time = time.time()
            
            # Signal invalidation (cancel if price moves 1 ATR adverse)
            if self.signal_state.status == "ACTIVE":
                atr = indicators.get('atr', 100)
                price = indicators.get('price')
                entry = self.signal_state.entry_price
                
                if price and entry:
                    if self.signal_state.direction == "LONG":
                        if price < entry - atr:
                            logger.warning(f"Signal INVALIDATED: LONG price moved 1 ATR adverse")
                            self.signal_state.reset()
                            return
                    elif self.signal_state.direction == "SHORT":
                        if price > entry + atr:
                            logger.warning(f"Signal INVALIDATED: SHORT price moved 1 ATR adverse")
                            self.signal_state.reset()
                            return
            
            # INSTITUTIONAL SIGNAL STATE MACHINE
            if self.signal_state.status == "IDLE":
                if active_result and active_result['signal_ready']:
                    # Get alpha checks
                    alpha_checks = active_result.get('alpha_checks', {})
                    velocity_check = alpha_checks.get('velocity', {})
                    
                    # Check for EXTREME volatility (zero-latency trigger)
                    obi_velocity = indicators.get('obi_velocity')
                    cvd_velocity = indicators.get('cvd_velocity')
                    
                    extreme_obi = abs(obi_velocity) > 0.05 if obi_velocity is not None else False
                    extreme_cvd = abs(cvd_velocity) > 0.05 if cvd_velocity is not None else False
                    
                    # Activate signal
                    self.signal_state.status = "ACTIVE"
                    self.signal_state.direction = active_direction
                    self.signal_state.entry_price = indicators.get('price')
                    self.signal_state.entry_time = current_time
                    self.signal_state.atr_at_entry = indicators.get('atr')
                    
                    if extreme_obi or extreme_cvd:
                        logger.warning(f"⚡ EXTREME VOLATILITY DETECTED ⚡")
                        logger.info(f"🚀🚀🚀 {self.display_name} ZERO-LATENCY: {active_direction} at ${self.signal_state.entry_price:.2f} (score: {active_result['score']}/100)")
                    else:
                        logger.info(f"🚀 {self.display_name} Signal ACTIVE: {active_direction} at ${self.signal_state.entry_price:.2f} (score: {active_result['score']}/100)")
                        logger.info(f"   Base: {active_result['base_score']}, Alpha Boost: +{active_result['alpha_boost']}")
                    
                    # Send Telegram alert
                    await self._send_signal_alert(indicators)
                    
            elif self.signal_state.status == "ACTIVE":
                # Active signals expire after 5 minutes
                elapsed = current_time - self.signal_state.entry_time
                if elapsed >= 300:
                    logger.info("Signal EXPIRED after 5 minutes")
                    self.signal_state.reset()
                    
        except Exception as e:
            logger.error(f"Error processing signal state with detector: {e}")
        """Process signal state machine with ZERO-LATENCY for extreme volatility"""
        try:
            # Check if all PRO SCALPER checklist items pass
            all_pass = all([
                checklist.get('regime', False),
                checklist.get('trend_align', False),
                checklist.get('cvd', False),
                checklist.get('obi', False),
                checklist.get('ema_dist', False),
                checklist.get('funding', False),
                checklist.get('gates', False),
                # PRO FILTERS (all must pass)
                checklist.get('volume_surge', False),
                checklist.get('clean_breakout', False),
                checklist.get('atr_expansion', False),
                checklist.get('rsi_momentum', False),
                checklist.get('ema_quality', False),
                checklist.get('time_filter', False)
            ])
            
            current_time = time.time()
            
            # Signal invalidation (cancel if price moves 1 ATR adverse)
            if self.signal_state.status == "ACTIVE":
                atr = indicators.get('atr', 100)
                price = indicators.get('price')
                entry = self.signal_state.entry_price
                
                if price and entry:
                    if self.signal_state.direction == "LONG":
                        if price < entry - atr:
                            logger.warning(f"Signal INVALIDATED: LONG price moved 1 ATR adverse (${price:.2f} < ${entry - atr:.2f})")
                            self.signal_state.reset()
                            return
                    elif self.signal_state.direction == "SHORT":
                        if price > entry + atr:
                            logger.warning(f"Signal INVALIDATED: SHORT price moved 1 ATR adverse (${price:.2f} > ${entry + atr:.2f})")
                            self.signal_state.reset()
                            return
            
            # ZERO-LATENCY STATE MACHINE with EXTREME VOLATILITY bypass
            if self.signal_state.status == "IDLE":
                if all_pass:
                    direction = checklist.get('trend_direction')
                    current_score = long_score if direction == 'LONG' else short_score
                    
                    # ZERO-LATENCY EXTREME VOLATILITY: Check if velocity is > 90th percentile
                    obi_velocity = indicators.get('obi_velocity')
                    cvd_velocity = indicators.get('cvd_velocity')
                    
                    # Extreme velocity thresholds (90th percentile approximation)
                    extreme_obi = abs(obi_velocity) > 0.05 if obi_velocity is not None else False
                    extreme_cvd = abs(cvd_velocity) > 0.05 if cvd_velocity is not None else False
                    
                    # If EXTREME volatility, bypass FORMING and go straight to ACTIVE
                    if extreme_obi or extreme_cvd:
                        self.signal_state.status = "ACTIVE"
                        self.signal_state.direction = direction
                        self.signal_state.entry_price = indicators.get('price')
                        self.signal_state.entry_time = current_time
                        self.signal_state.atr_at_entry = indicators.get('atr')
                        
                        logger.warning(f"⚡ EXTREME VOLATILITY DETECTED ⚡")
                        logger.warning(f"   OBI Velocity: {obi_velocity:.6f}, CVD Velocity: {cvd_velocity:.6f}")
                        logger.info(f"🚀🚀🚀 {self.display_name} ZERO-LATENCY SIGNAL: {direction} at ${self.signal_state.entry_price:.2f} (score: {current_score}/100)")
                        
                        # Send Telegram alert
                        await self._send_signal_alert(indicators)
                    else:
                        # Normal path: Instant activation (already zero-latency)
                        self.signal_state.status = "ACTIVE"
                        self.signal_state.direction = direction
                        self.signal_state.entry_price = indicators.get('price')
                        self.signal_state.entry_time = current_time
                        self.signal_state.atr_at_entry = indicators.get('atr')
                        
                        logger.info(f"🚀 {self.display_name} Signal ACTIVE: {direction} at ${self.signal_state.entry_price:.2f} (score: {current_score}/100)")
                        
                        # Send Telegram alert
                        await self._send_signal_alert(indicators)
                        
            elif self.signal_state.status == "ACTIVE":
                # Active signals expire after 5 minutes
                elapsed = current_time - self.signal_state.entry_time
                if elapsed >= 300:
                    logger.info("Signal EXPIRED after 5 minutes")
                    self.signal_state.reset()
                    
        except Exception as e:
            logger.error(f"Error processing signal state: {e}")
    
    async def _send_signal_alert(self, indicators: Dict):
        """Send Telegram alert for active signal with ADAPTIVE TARGETS"""
        try:
            atr = indicators.get('atr', 100)
            entry = self.signal_state.entry_price
            direction = self.signal_state.direction
            
            # ALPHA ENHANCEMENT: Adaptive targets based on trend strength
            trend_strength = indicators.get('trend_strength')
            
            # Import alpha detector for adaptive target calculation
            from signal_detector_alpha import SignalDetector
            alpha_detector = SignalDetector()
            adaptive_targets = alpha_detector.calculate_adaptive_targets(atr, trend_strength=trend_strength)
            
            # Use adaptive multipliers instead of static values
            tp1_mult = adaptive_targets['tp1_multiplier']
            tp2_mult = adaptive_targets['tp2_multiplier']
            sl_mult = adaptive_targets['sl_multiplier']
            
            logger.info(f"🎯 Adaptive Targets: {adaptive_targets['regime_detail']}")
            logger.info(f"   TP1: {tp1_mult}x ATR, TP2: {tp2_mult}x ATR, SL: {sl_mult}x ATR")
            
            if direction == "LONG":
                sl = entry - (sl_mult * atr)
                tp1 = entry + (tp1_mult * atr)
                tp2 = entry + (tp2_mult * atr)
            else:  # SHORT
                sl = entry + (sl_mult * atr)
                tp1 = entry - (tp1_mult * atr)
                tp2 = entry - (tp2_mult * atr)
            
            self.alert_manager.send_signal_alert(
                direction=direction,
                confidence=100,  # All checklist passed
                entry=entry,
                stop_loss=sl,
                tp1=tp1,
                tp2=tp2,
                symbol=self.display_name
            )
            
        except Exception as e:
            logger.error(f"Error sending signal alert: {e}")
    
    def get_status(self) -> Dict:
        """Get current engine status for WebSocket broadcast"""
        try:
            indicators = self._calculate_indicators()
            checklist = self._build_checklist(indicators)
            
            # Calculate proper gradient scores for LONG and SHORT independently
            long_score = self._calculate_signal_score('LONG', indicators, checklist)
            short_score = self._calculate_signal_score('SHORT', indicators, checklist)
            
            # Build LONG hard gates (bullish requirements)
            long_gates = self._build_hard_gates('LONG', indicators, checklist)
            
            # Build SHORT hard gates (bearish requirements)
            short_gates = self._build_hard_gates('SHORT', indicators, checklist)
            
            # Format indicators to match frontend expectations
            formatted_indicators = {
                'ema': {
                    '1m': {
                        'ema20': indicators.get('ema20_1m'),
                        'ema50': indicators.get('ema50_1m')
                    },
                    '5m': {
                        'ema20': indicators.get('ema20_5m'),
                        'ema50': indicators.get('ema50_5m')
                    },
                    '15m': {
                        'ema20': indicators.get('ema20_15m'),
                        'ema50': indicators.get('ema50_15m')
                    }
                },
                'atr_5m': indicators.get('atr'),
                'rsi_5m': indicators.get('rsi'),
                'cvd': indicators.get('cvd', {
                    '1m': None,
                    '5m': None
                }),
                'obi': indicators.get('obi'),
                'spread': indicators.get('spread'),
                'depth': indicators.get('depth'),
                # ALPHA indicators
                'vwap': indicators.get('vwap'),
                'trend_strength': indicators.get('trend_strength'),
                'obi_velocity': indicators.get('obi_velocity'),
                'cvd_velocity': indicators.get('cvd_velocity'),
                'bollinger': indicators.get('bollinger'),
                'taker_buy_ratio': indicators.get('taker_buy_ratio')
            }
            
            # Build signal structure
            signals_data = {
                'short': {
                    'score': short_score,
                    'hard_gates': short_gates,
                    'signal_ready': self.signal_state.status == 'ACTIVE' and self.signal_state.direction == 'SHORT',
                    'quality': 'HIGH' if short_score >= 80 else 'MEDIUM' if short_score >= 65 else 'LOW'
                },
                'long': {
                    'score': long_score,
                    'hard_gates': long_gates,
                    'signal_ready': self.signal_state.status == 'ACTIVE' and self.signal_state.direction == 'LONG',
                    'quality': 'HIGH' if long_score >= 80 else 'MEDIUM' if long_score >= 65 else 'LOW'
                }
            }
            
            # Signal status for countdown
            signal_status_data = {
                'state': self.signal_state.status,
                'direction': self.signal_state.direction,
                'forming_remaining': 0,  # No FORMING state anymore (zero-latency)
                'active_remaining': max(0, 300 - (time.time() - self.signal_state.entry_time)) if self.signal_state.status == 'ACTIVE' and self.signal_state.entry_time else 0,
                'entry_min': self.signal_state.entry_price,
                'entry_max': self.signal_state.entry_price
            }
            
            return {
                'symbol': self.symbol,
                'connected': True,
                'regime': checklist.get('regime_direction', 'RANGING'),
                'current_price': self.current_price,
                'candle_counts': {
                    '1m': len(self.candles_1m),
                    '5m': len(self.candles_5m),
                    '15m': len(self.candles_15m)
                },
                'indicators': formatted_indicators,
                'gates': {
                    'all_pass': checklist.get('gates', False),
                    'spread': {
                        'pass': (indicators.get('spread', 999) < checklist.get('spread_threshold', 1.5)) if indicators.get('spread') is not None else False,
                        'value': indicators.get('spread', 0),
                        'threshold': checklist.get('spread_threshold', 1.5),
                        'mode': 'dynamic' if self.spread_stats.count() >= 10 else 'static'
                    },
                    'depth': {
                        'pass': (indicators.get('depth', 0) > checklist.get('depth_threshold', 500000)) if indicators.get('depth') is not None else False,
                        'value': indicators.get('depth', 0),
                        'threshold': checklist.get('depth_threshold', 500000),
                        'mode': 'dynamic' if self.depth_stats.count() >= 10 else 'static'
                    },
                    'ticker_staleness': {
                        'age_ms': (time.time() - self.last_ticker_time) * 1000 if self.last_ticker_time else None,
                        'pass': ((time.time() - self.last_ticker_time) * 1000 < 2000) if self.last_ticker_time else False
                    }
                },
                'signals': signals_data,
                'signal_status': signal_status_data
            }
            
        except Exception as e:
            logger.error(f"Error getting status: {e}")
            return {'error': str(e)}
    
    def _calculate_signal_score(self, direction: str, indicators: Dict, checklist: Dict) -> int:
        """Calculate gradient score 0-100 for a signal direction"""
        score = 0
        
        # 1. Regime alignment (20 points) - must match direction
        regime = checklist.get('regime_direction', 'RANGING')
        if direction == 'LONG' and regime == 'BULL':
            score += 20
        elif direction == 'SHORT' and regime == 'BEAR':
            score += 20
        elif checklist.get('regime', False):
            score += 10  # Trending but wrong direction
        
        # 2. Multi-TF alignment (20 points)
        if checklist.get('trend_align', False):
            if checklist.get('trend_direction') == ('BULL' if direction == 'LONG' else 'BEAR'):
                score += 20
            else:
                score += 5  # Aligned but wrong direction
        
        # 3. CVD/Taker buy ratio (15 points)
        taker_ratio = indicators.get('taker_buy_ratio') or 0.5
        if direction == 'LONG':
            if taker_ratio > 0.65:
                score += 15
            elif taker_ratio > 0.60:
                score += 10
            elif taker_ratio > 0.50:
                score += 5
        else:  # SHORT
            if taker_ratio < 0.35:
                score += 15
            elif taker_ratio < 0.40:
                score += 10
            elif taker_ratio < 0.50:
                score += 5
        
        # 4. OBI (15 points)
        obi = indicators.get('obi') or 0
        if direction == 'LONG':
            if obi > 0.20:
                score += 15
            elif obi > 0.15:
                score += 10
            elif obi > 0:
                score += 5
        else:  # SHORT
            if obi < -0.20:
                score += 15
            elif obi < -0.15:
                score += 10
            elif obi < 0:
                score += 5
        
        # 5. EMA distance (10 points)
        if checklist.get('ema_dist', False):
            score += 10
        
        # 6. RSI position (10 points)
        rsi = indicators.get('rsi') or 50
        if 40 <= rsi <= 60:
            score += 10
        elif 35 <= rsi <= 65:
            score += 7
        elif 30 <= rsi <= 70:
            score += 5
        
        # 7. Gates (10 points)
        if checklist.get('gates', False):
            score += 10
        
        return min(100, score)
    
    def _build_hard_gates(self, direction: str, indicators: Dict, checklist: Dict) -> Dict:
        """Build direction-specific hard gates"""
        regime = checklist.get('regime_direction', 'RANGING')
        rsi = indicators.get('rsi') or 50  # Default to 50 if None
        obi = indicators.get('obi') or 0  # Default to 0 if None
        taker_ratio = indicators.get('taker_buy_ratio') or 0.5  # Default to 0.5 if None
        atr = indicators.get('atr') or 100  # Default to 100 if None
        funding = self.funding_rate or 0  # Get funding rate
        
        # Direction-specific checks
        if direction == 'LONG':
            regime_pass = regime == 'BULL'
            cvd_pass = taker_ratio > 0.57
            obi_pass = obi > 0.12
            regime_detail = regime if regime == 'BULL' else f'{regime} (need BULL)'
        else:  # SHORT
            regime_pass = regime == 'BEAR'
            cvd_pass = taker_ratio < 0.43
            obi_pass = obi < -0.12
            regime_detail = regime if regime == 'BEAR' else f'{regime} (need BEAR)'
        
        return {
            'regime_filter': {
                'pass': regime_pass,
                'detail': regime_detail
            },
            'rsi_filter': {
                'pass': 30 <= rsi <= 70 if rsi is not None else False,
                'detail': f"{rsi:.0f}" + (' (need 30-70)' if rsi and not (30 <= rsi <= 70) else '') if rsi else 'N/A'
            },
            'ema_proximity': {
                'pass': checklist.get('ema_dist', False),
                'detail': f"{checklist.get('ema_dist_value', 0):.2f}%"
            },
            'spread': {
                'pass': checklist.get('gates', False),
                'detail': f"{indicators.get('spread', 0):.2f} bps" if indicators.get('spread') is not None else 'N/A'
            },
            'directional_alignment': {
                'pass': cvd_pass and obi_pass,
                'detail': f"CVD {taker_ratio:.3f}, OBI {obi:.3f}" if obi is not None else f"CVD {taker_ratio:.3f}, OBI N/A"
            },
            'atr_sufficient': {
                'pass': atr > 100 if atr else False,
                'detail': f"${atr:.0f}" if atr else 'N/A'
            },
            'funding_filter': {
                'pass': abs(funding) < 0.0002,  # 0.02%
                'detail': f"{funding:.4%}" + (' ✓' if abs(funding) < 0.0002 else ' (need <0.02%)')
            },
            'all_pass': regime_pass and (30 <= rsi <= 70) and checklist.get('ema_dist', False) and checklist.get('gates', False) and cvd_pass and obi_pass and atr > 100 and abs(funding) < 0.0002
        }
