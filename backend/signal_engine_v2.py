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
from state_persistence import StatePersistence  # STATE PERSISTENCE: Anti-amnesia
from trade_tracker import TradeTracker  # TRADE ACCOUNTABILITY: Track signal performance

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
        self.tp1 = None
        self.tp2 = None
        self.stop_loss = None
        self.score = None  # Actual signal score
        
    def reset(self):
        self.status = "IDLE"
        self.direction = None
        self.entry_price = None
        self.entry_time = None
        self.forming_start = None
        self.atr_at_entry = None
        self.tp1 = None
        self.tp2 = None
        self.stop_loss = None
        self.score = None

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
        
        # REFACTOR: Cache detector results for get_status()
        self.last_long_result = None
        self.last_short_result = None
        self.last_regime = None
        
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
        
        # CRITICAL: Track real-time forming candle volume
        self.forming_1m_volume = 0
        self.forming_1m_start_time = None
        
        # COOLDOWN: Prevent signal spam
        self.last_signal_time = {}  # {direction: timestamp}
        self.signal_cooldown = 300  # 5 minutes between same-direction signals
        
        # STATE PERSISTENCE: Anti-amnesia
        self.state_persistence = StatePersistence(self.symbol)
        self._periodic_save_task = None
        
        # TRADE ACCOUNTABILITY: Track signal performance
        self.tracker = TradeTracker(self.symbol)
        
        # Load previous state to restore context
        self._load_state()
        
        # Staleness tracking
        self.last_ticker_time = None
        
        # EVENT-DRIVEN ARCHITECTURE: Throttle mechanism
        self.last_signal_check_time = 0
        self.signal_check_throttle = 0.1  # Check max every 100ms (10x faster than 1s polling)
    
    def _load_state(self):
        """Load previous state from disk to restore context (anti-amnesia)"""
        try:
            state_data = self.state_persistence.load_state()
            
            if not state_data:
                logger.info(f"{self.display_name}: No previous state found, starting fresh")
                return
            
            # Restore recent_trades
            if 'recent_trades' in state_data:
                for trade in state_data['recent_trades']:
                    self.recent_trades.append(trade)
                logger.info(f"{self.display_name}: Restored {len(state_data['recent_trades'])} trades from state")
            
            # Restore CVD history (for indicators.py)
            if 'cvd_history' in state_data:
                cvd_history = state_data['cvd_history']
                if hasattr(self.indicators, 'cvd_history'):
                    for item in cvd_history:
                        self.indicators.cvd_history.append(item)
                    logger.info(f"{self.display_name}: Restored {len(cvd_history)} CVD history entries")
            
            # Restore OBI history (for indicators.py)
            if 'obi_history' in state_data:
                obi_history = state_data['obi_history']
                if hasattr(self.indicators, 'obi_history'):
                    for item in obi_history:
                        self.indicators.obi_history.append(item)
                    logger.info(f"{self.display_name}: Restored {len(obi_history)} OBI history entries")
            
            # Restore last signal time (for cooldown)
            if 'last_signal_time' in state_data:
                self.last_signal_time = state_data['last_signal_time']
                logger.info(f"{self.display_name}: Restored signal cooldown timestamps")
            
            # Restore taker buy ratio buffer
            if 'taker_buy_ratio_buffer' in state_data:
                for item in state_data['taker_buy_ratio_buffer']:
                    self.taker_buy_ratio_buffer.append(item)
                logger.info(f"{self.display_name}: Restored {len(state_data['taker_buy_ratio_buffer'])} taker ratio entries")
            
            logger.info(f"{self.display_name}: State restoration complete")
            
        except Exception as e:
            logger.error(f"{self.display_name}: Error loading state: {e}")
    
    def _get_state_to_save(self) -> Dict:
        """Get current state for saving to disk"""
        try:
            state = {
                'symbol': self.symbol,
                'timestamp': time.time(),
                # Recent trades (keep last 10000 for reasonable file size)
                'recent_trades': list(self.recent_trades)[-10000:],
                # Signal cooldown timestamps
                'last_signal_time': self.last_signal_time,
                # Taker ratio buffer
                'taker_buy_ratio_buffer': list(self.taker_buy_ratio_buffer)
            }
            
            # Save CVD history if available
            if hasattr(self.indicators, 'cvd_history'):
                state['cvd_history'] = list(self.indicators.cvd_history)
            
            # Save OBI history if available
            if hasattr(self.indicators, 'obi_history'):
                state['obi_history'] = list(self.indicators.obi_history)
            
            return state
            
        except Exception as e:
            logger.error(f"{self.display_name}: Error building state: {e}")
            return {}
    
    async def save_state(self):
        """Save current state to disk (called periodically and on shutdown)"""
        try:
            state_data = self._get_state_to_save()
            if state_data:
                success = self.state_persistence.save_state(state_data)
                if success:
                    logger.debug(f"{self.display_name}: State saved successfully")
                return success
            return False
        except Exception as e:
            logger.error(f"{self.display_name}: Error saving state: {e}")
            return False
    
    async def _periodic_save(self):
        """Background task to save state every 60 seconds"""
        while True:
            try:
                await asyncio.sleep(60)  # Save every 60 seconds
                await self.save_state()
            except asyncio.CancelledError:
                # Final save on cancellation
                logger.info(f"{self.display_name}: Periodic save task cancelled, performing final save")
                await self.save_state()
                break
            except Exception as e:
                logger.error(f"{self.display_name}: Error in periodic save: {e}")
        
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
        
        # 6. Start periodic state saving (anti-amnesia)
        self._periodic_save_task = asyncio.create_task(self._periodic_save())
        logger.info(f"{self.display_name}: Periodic state save task started (every 60s)")
        
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
                    
                    # CRITICAL: Reset forming volume when 1m candle confirms
                    self.forming_1m_volume = 0
                    self.forming_1m_start_time = candle.timestamp
                    
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
            
            # EVENT-DRIVEN: Trigger signal check (async, non-blocking)
            asyncio.create_task(self._check_signals_event_driven())
                    
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
            
            # CRITICAL: Accumulate volume for forming 1m candle
            if size:
                self.forming_1m_volume += size
            
            # Update current price from trade
            price = data.get('px')
            if price:
                self.current_price = float(price)
                
                # TRADE ACCOUNTABILITY: Update active trade with current price
                self.tracker.update(self.current_price)
            
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
            
            # EVENT-DRIVEN: Trigger signal check (async, non-blocking)
            asyncio.create_task(self._check_signals_event_driven())
                
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
            
            # Calculate indicators with HYBRID data (live + confirmed)
            hybrid_indicators = self._calculate_indicators_live()
            live_ind = hybrid_indicators.get('live', {})
            conf_ind = hybrid_indicators.get('confirmed', {})
            
            # Update gate states with current market data and DYNAMIC thresholds
            # Use LIVE indicators for gate checks (real-time responsiveness)
            spread = live_ind.get('spread')
            depth = live_ind.get('depth')
            orderbook_timestamp = time.time() if self.last_orderbook else None
            
            # Calculate dynamic thresholds from rolling stats
            spread_threshold = self.spread_stats.percentile(90) if self.spread_stats.count() >= 10 else 2.5
            depth_threshold = self.depth_stats.percentile(10) if self.depth_stats.count() >= 10 else 30000
            
            # Update gates with dynamic thresholds
            self.regime_detector.check_spread_gate(spread, threshold=spread_threshold)
            self.regime_detector.check_depth_gate(depth, threshold=depth_threshold)
            if orderbook_timestamp:
                self.regime_detector.check_data_staleness(orderbook_timestamp)
            
            # Detect regime using CONFIRMED indicators (prevents repainting)
            candles_5m_list = list(self.candles_5m)
            candles_15m_list = list(self.candles_15m)
            regime = self.regime_detector.detect_regime(
                candles_5m_list,
                candles_15m_list,
                conf_ind.get('ema20_5m'),
                conf_ind.get('ema50_5m'),
                conf_ind.get('ema20_15m'),
                conf_ind.get('ema50_15m'),
                conf_ind.get('atr')
            )
            
            # CRITICAL: Use institutional SignalDetector for LONG signals
            # Use LIVE indicators for low-latency entry triggers
            long_result = self.detector.detect_signal_with_alpha(
                direction=SignalDirection.LONG,
                regime=regime,
                ema20_1m=live_ind.get('ema20_1m'),
                ema50_1m=live_ind.get('ema50_1m'),
                ema20_5m=live_ind.get('ema20_5m'),
                ema50_5m=live_ind.get('ema50_5m'),
                ema20_15m=live_ind.get('ema20_15m'),
                ema50_15m=live_ind.get('ema50_15m'),
                cvd_5m=live_ind.get('cvd', {}).get('5m'),
                obi=live_ind.get('obi'),
                current_price=live_ind.get('price'),
                rsi_5m=live_ind.get('rsi'),
                spread=live_ind.get('spread'),
                atr=live_ind.get('atr'),
                # ALPHA inputs
                obi_velocity=live_ind.get('obi_velocity'),
                cvd_velocity=live_ind.get('cvd_velocity'),
                bollinger=live_ind.get('bollinger'),
                vwap=live_ind.get('vwap'),
                trend_strength=live_ind.get('trend_strength'),
                hurst=None  # Using trend_strength instead
            )
            
            # CRITICAL: Use institutional SignalDetector for SHORT signals
            short_result = self.detector.detect_signal_with_alpha(
                direction=SignalDirection.SHORT,
                regime=regime,
                ema20_1m=live_ind.get('ema20_1m'),
                ema50_1m=live_ind.get('ema50_1m'),
                ema20_5m=live_ind.get('ema20_5m'),
                ema50_5m=live_ind.get('ema50_5m'),
                ema20_15m=live_ind.get('ema20_15m'),
                ema50_15m=live_ind.get('ema50_15m'),
                cvd_5m=live_ind.get('cvd', {}).get('5m'),
                obi=live_ind.get('obi'),
                current_price=live_ind.get('price'),
                rsi_5m=live_ind.get('rsi'),
                spread=live_ind.get('spread'),
                atr=live_ind.get('atr'),
                # ALPHA inputs
                obi_velocity=live_ind.get('obi_velocity'),
                cvd_velocity=live_ind.get('cvd_velocity'),
                bollinger=live_ind.get('bollinger'),
                vwap=live_ind.get('vwap'),
                trend_strength=live_ind.get('trend_strength'),
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
            
            # REFACTOR: Cache detector results for get_status()
            self.last_long_result = long_result
            self.last_short_result = short_result
            self.last_regime = regime
            
            # Process signal state machine (use LIVE indicators)
            await self._process_signal_state_with_detector(
                active_result, 
                active_direction, 
                live_ind,  # Use LIVE indicators for state machine
                long_result,
                short_result
            )
            
        except Exception as e:
            logger.error(f"Error in event-driven signal check: {e}")
    
    def _calculate_indicators_live(self) -> Dict:
        """
        Calculate indicators with HYBRID DATA LOGIC (Institutional-Grade)
        
        Returns TWO sets of indicators to prevent repainting:
        - CONFIRMED: Uses only closed candles for regime/structure (stable)
        - LIVE: Uses forming candles for entry triggers (zero-latency)
        
        This prevents "ghost signals" caused by regime flickering on forming candles.
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
                forming_candle_1m.volume = self.forming_1m_volume  # FIXED: Use real-time volume instead of 0
                
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
            
            # LIVE indicators for real-time display and entry triggers
            live_indicators = {
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
            
            # CONFIRMED indicators using closed candles only (for stable regime detection)
            ema20_5m_conf = self.indicators.calculate_ema(candles_5m_list, 20)
            ema50_5m_conf = self.indicators.calculate_ema(candles_5m_list, 50)
            ema20_15m_conf = self.indicators.calculate_ema(candles_15m_list, 20)
            ema50_15m_conf = self.indicators.calculate_ema(candles_15m_list, 50)
            
            confirmed_indicators = {
                'ema20_5m': ema20_5m_conf,
                'ema50_5m': ema50_5m_conf,
                'ema20_15m': ema20_15m_conf,
                'ema50_15m': ema50_15m_conf,
                'atr': atr if atr and atr > 0 else 100
            }
            
            # Return HYBRID structure: live for triggers, confirmed for regime
            return {
                'live': live_indicators,
                'confirmed': confirmed_indicators
            }
            
        except Exception as e:
            logger.error(f"Error calculating live indicators: {e}")
            return {'live': {}, 'confirmed': {}}
    
    def _calculate_indicators(self) -> Dict:
        """
        LEGACY: Calculate indicators (kept for get_status compatibility)
        Use _calculate_indicators_live() for signal processing
        """
        return self._calculate_indicators_live()
    
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
                    # COOLDOWN CHECK: Prevent signal spam
                    last_same_dir_signal = self.last_signal_time.get(active_direction, 0)
                    time_since_last = current_time - last_same_dir_signal
                    
                    if time_since_last < self.signal_cooldown:
                        # Still in cooldown period - skip this signal
                        remaining = self.signal_cooldown - time_since_last
                        logger.debug(f"{self.display_name}: {active_direction} signal blocked by cooldown ({remaining:.0f}s remaining)")
                        return
                    
                    # Get alpha checks
                    alpha_checks = active_result.get('alpha_checks', {})
                    velocity_check = alpha_checks.get('velocity', {})
                    
                    # Check for EXTREME volatility (zero-latency trigger)
                    obi_velocity = indicators.get('obi_velocity')
                    cvd_velocity = indicators.get('cvd_velocity')
                    
                    extreme_obi = abs(obi_velocity) > 0.05 if obi_velocity is not None else False
                    extreme_cvd = abs(cvd_velocity) > 0.05 if cvd_velocity is not None else False
                    
                    # Calculate TP/SL levels
                    atr = indicators.get('atr', 100)
                    entry = indicators.get('price')
                    trend_strength = indicators.get('trend_strength')
                    
                    # Get adaptive targets (SignalDetector already imported at top)
                    adaptive_targets = self.detector.calculate_adaptive_targets(atr, trend_strength=trend_strength)
                    
                    tp1_mult = adaptive_targets['tp1_multiplier']
                    tp2_mult = adaptive_targets['tp2_multiplier']
                    sl_mult = adaptive_targets['sl_multiplier']
                    
                    if active_direction == "LONG":
                        sl = entry - (sl_mult * atr)
                        tp1 = entry + (tp1_mult * atr)
                        tp2 = entry + (tp2_mult * atr)
                    else:  # SHORT
                        sl = entry + (sl_mult * atr)
                        tp1 = entry - (tp1_mult * atr)
                        tp2 = entry - (tp2_mult * atr)
                    
                    # Activate signal
                    self.signal_state.status = "ACTIVE"
                    self.signal_state.direction = active_direction
                    self.signal_state.entry_price = entry
                    self.signal_state.entry_time = current_time
                    self.signal_state.atr_at_entry = atr
                    self.signal_state.tp1 = tp1
                    self.signal_state.tp2 = tp2
                    self.signal_state.stop_loss = sl
                    
                    # Store score for alert
                    self.signal_state.score = active_result['score']
                    
                    # Update cooldown timestamp
                    self.last_signal_time[active_direction] = current_time
                    
                    if extreme_obi or extreme_cvd:
                        logger.warning(f"⚡ EXTREME VOLATILITY DETECTED ⚡")
                        logger.info(f"🚀🚀🚀 {self.display_name} ZERO-LATENCY: {active_direction} at ${self.signal_state.entry_price:.2f} (score: {active_result['score']}/100)")
                    else:
                        logger.info(f"🚀 {self.display_name} Signal ACTIVE: {active_direction} at ${self.signal_state.entry_price:.2f} (score: {active_result['score']}/100)")
                        logger.info(f"   Base: {active_result['base_score']}, Alpha Boost: +{active_result['alpha_boost']}")
                    
                    # Send Telegram alert
                    await self._send_signal_alert(indicators)
                    
                    # TRADE ACCOUNTABILITY: Start tracking this trade
                    self.tracker.start_trade({
                        'direction': active_direction,
                        'entry_price': entry,
                        'tp1': tp1,
                        'sl': sl
                    })
                    
            elif self.signal_state.status == "ACTIVE":
                # Active signals expire after 1 minute (scalping)
                elapsed = current_time - self.signal_state.entry_time
                if elapsed >= 60:
                    logger.info("Signal EXPIRED after 1 minute")
                    self.signal_state.reset()
                    
        except Exception as e:
            logger.error(f"Error processing signal state with detector: {e}")
    
    async def _send_signal_alert(self, indicators: Dict):
        """Send Telegram alert for active signal with ADAPTIVE TARGETS"""
        try:
            atr = indicators.get('atr', 100)
            entry = self.signal_state.entry_price
            direction = self.signal_state.direction
            
            # ALPHA ENHANCEMENT: Adaptive targets based on trend strength
            trend_strength = indicators.get('trend_strength')
            
            # Calculate adaptive targets (SignalDetector already imported at top)
            adaptive_targets = self.detector.calculate_adaptive_targets(atr, trend_strength=trend_strength)
            
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
                confidence=self.signal_state.score,  # Use actual score, not hardcoded 100
                entry=entry,
                stop_loss=sl,
                tp1=tp1,
                tp2=tp2,
                symbol=self.display_name
            )
            
        except Exception as e:
            logger.error(f"Error sending signal alert: {e}")
    
    def get_status(self) -> Dict:
        """Get current engine status for WebSocket broadcast - REFACTORED to use SignalDetector"""
        try:
            # Unpack hybrid indicators (live + confirmed)
            hybrid_indicators = self._calculate_indicators()
            live_ind = hybrid_indicators.get('live', {})
            conf_ind = hybrid_indicators.get('confirmed', {})
            
            # Always calculate fresh detector results for get_status()
            # The cached results are primarily for the signal state machine
            candles_5m_list = list(self.candles_5m)
            candles_15m_list = list(self.candles_15m)
            
            # Detect regime using CONFIRMED indicators (prevents repainting)
            regime = self.regime_detector.detect_regime(
                candles_5m_list,
                candles_15m_list,
                conf_ind.get('ema20_5m'),
                conf_ind.get('ema50_5m'),
                conf_ind.get('ema20_15m'),
                conf_ind.get('ema50_15m'),
                conf_ind.get('atr')
            )
            
            # Calculate signals using detector with LIVE indicators
            long_result = self.detector.detect_signal_with_alpha(
                direction=SignalDirection.LONG,
                regime=regime,
                ema20_1m=live_ind.get('ema20_1m'),
                ema50_1m=live_ind.get('ema50_1m'),
                ema20_5m=live_ind.get('ema20_5m'),
                ema50_5m=live_ind.get('ema50_5m'),
                ema20_15m=live_ind.get('ema20_15m'),
                ema50_15m=live_ind.get('ema50_15m'),
                cvd_5m=live_ind.get('cvd', {}).get('5m'),
                obi=live_ind.get('obi'),
                current_price=live_ind.get('price'),
                rsi_5m=live_ind.get('rsi'),
                spread=live_ind.get('spread'),
                atr=live_ind.get('atr'),
                obi_velocity=live_ind.get('obi_velocity'),
                cvd_velocity=live_ind.get('cvd_velocity'),
                bollinger=live_ind.get('bollinger'),
                vwap=live_ind.get('vwap'),
                trend_strength=live_ind.get('trend_strength'),
                hurst=None
            )
            
            short_result = self.detector.detect_signal_with_alpha(
                direction=SignalDirection.SHORT,
                regime=regime,
                ema20_1m=live_ind.get('ema20_1m'),
                ema50_1m=live_ind.get('ema50_1m'),
                ema20_5m=live_ind.get('ema20_5m'),
                ema50_5m=live_ind.get('ema50_5m'),
                ema20_15m=live_ind.get('ema20_15m'),
                ema50_15m=live_ind.get('ema50_15m'),
                cvd_5m=live_ind.get('cvd', {}).get('5m'),
                obi=live_ind.get('obi'),
                current_price=live_ind.get('price'),
                rsi_5m=live_ind.get('rsi'),
                spread=live_ind.get('spread'),
                atr=live_ind.get('atr'),
                obi_velocity=live_ind.get('obi_velocity'),
                cvd_velocity=live_ind.get('cvd_velocity'),
                bollinger=live_ind.get('bollinger'),
                vwap=live_ind.get('vwap'),
                trend_strength=live_ind.get('trend_strength'),
                hurst=None
            )
            
            long_score = long_result['score']
            short_score = short_result['score']
            long_gates = self._map_detector_to_hard_gates(long_result, 'LONG', live_ind)
            short_gates = self._map_detector_to_hard_gates(short_result, 'SHORT', live_ind)
            regime_str = str(regime.value) if regime else 'RANGING'
            
            # Format indicators to match frontend expectations (use LIVE for real-time display)
            formatted_indicators = {
                'ema': {
                    '1m': {
                        'ema20': live_ind.get('ema20_1m'),
                        'ema50': live_ind.get('ema50_1m')
                    },
                    '5m': {
                        'ema20': live_ind.get('ema20_5m'),
                        'ema50': live_ind.get('ema50_5m')
                    },
                    '15m': {
                        'ema20': live_ind.get('ema20_15m'),
                        'ema50': live_ind.get('ema50_15m')
                    }
                },
                'atr_5m': live_ind.get('atr'),
                'rsi_5m': live_ind.get('rsi'),
                'cvd': live_ind.get('cvd', {
                    '1m': None,
                    '5m': None
                }),
                'obi': live_ind.get('obi'),
                'spread': live_ind.get('spread'),
                'depth': live_ind.get('depth'),
                # ALPHA indicators
                'vwap': live_ind.get('vwap'),
                'trend_strength': live_ind.get('trend_strength'),
                'obi_velocity': live_ind.get('obi_velocity'),
                'cvd_velocity': live_ind.get('cvd_velocity'),
                'bollinger': live_ind.get('bollinger'),
                'taker_buy_ratio': live_ind.get('taker_buy_ratio')
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
                'active_remaining': max(0, 60 - (time.time() - self.signal_state.entry_time)) if self.signal_state.status == 'ACTIVE' and self.signal_state.entry_time else 0,
                'entry_min': self.signal_state.entry_price,
                'entry_max': self.signal_state.entry_price,
                'tp1': self.signal_state.tp1,
                'tp2': self.signal_state.tp2,
                'stop_loss': self.signal_state.stop_loss
            }
            
            return {
                'symbol': self.symbol,
                'connected': True,
                'regime': regime_str,
                'current_price': self.current_price,
                'candle_counts': {
                    '1m': len(self.candles_1m),
                    '5m': len(self.candles_5m),
                    '15m': len(self.candles_15m)
                },
                'indicators': formatted_indicators,
                'gates': {
                    'all_pass': self.regime_detector.spread_gate.current_state and self.regime_detector.depth_gate.current_state,
                    'spread': {
                        'pass': self.regime_detector.spread_gate.current_state,
                        'value': live_ind.get('spread', 0),
                        'threshold': self.spread_stats.percentile(90) if self.spread_stats.count() >= 10 else 2.5,
                        'mode': 'dynamic' if self.spread_stats.count() >= 10 else 'static'
                    },
                    'depth': {
                        'pass': self.regime_detector.depth_gate.current_state,
                        'value': live_ind.get('depth', 0),
                        'threshold': self.depth_stats.percentile(10) if self.depth_stats.count() >= 10 else 30000,
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
    

    def _map_detector_to_hard_gates(self, detector_result: Dict, direction: str, indicators: Dict) -> Dict:
        """Map SignalDetector results to frontend's expected hard_gates format"""
        try:
            alpha_checks = detector_result.get('alpha_checks', {})
            breakdown = detector_result.get('breakdown', {})
            
            # Extract regime from breakdown
            regime_detail = breakdown.get('regime', {}).get('detail', 'RANGING')
            regime_pass = breakdown.get('regime', {}).get('points', 0) > 0
            
            # Extract RSI info
            rsi_val = indicators.get('rsi', 50)
            rsi_pass = 30 <= rsi_val <= 70 if rsi_val is not None else False
            rsi_detail = f"{rsi_val:.0f}" if rsi_val else "N/A"
            if not rsi_pass:
                rsi_detail += " (need 30-70)"
            
            # Extract CVD/OBI alignment with None checks
            cvd_val = indicators.get('cvd', {}).get('5m', 0) or 0
            obi_val = indicators.get('obi', 0) or 0
            
            if direction == 'LONG':
                cvd_pass = cvd_val > 0.08
                obi_pass = obi_val > 0.1
            else:  # SHORT
                cvd_pass = cvd_val < -0.08
                obi_pass = obi_val < -0.1
            
            alignment_pass = cvd_pass and obi_pass
            
            # Extract spread check
            spread_val = indicators.get('spread', 0)
            spread_pass = spread_val < 5 if spread_val is not None else False
            
            # Build hard_gates structure
            return {
                'regime_filter': {
                    'pass': regime_pass,
                    'detail': regime_detail
                },
                'rsi_filter': {
                    'pass': rsi_pass,
                    'detail': rsi_detail
                },
                'ema_proximity': {
                    'pass': True,  # Detector handles this internally
                    'detail': breakdown.get('trends', {}).get('detail', 'N/A')
                },
                'spread': {
                    'pass': spread_pass,
                    'detail': f"{spread_val:.2f} bps" if spread_val is not None else "N/A"
                },
                'cvd/obi_alignment': {
                    'pass': alignment_pass,
                    'detail': f"CVD {cvd_val:.3f}, OBI {obi_val:.3f}"
                },
                'all_pass': detector_result.get('signal_ready', False)
            }
        except Exception as e:
            logger.error(f"Error mapping detector to hard gates: {e}")
            return {}

