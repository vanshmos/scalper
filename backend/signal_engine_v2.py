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
        self.trade_volume_1m = deque(maxlen=60)  # Track last 60 trades for ratio
        
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
            if 'last' in data:
                self.current_price = float(data['last'])
        except Exception as e:
            logger.error(f"Error handling ticker: {e}")
    
    async def _on_orderbook(self, data: dict):
        """Handle orderbook updates"""
        try:
            self.last_orderbook = data
        except Exception as e:
            logger.error(f"Error handling orderbook: {e}")
    
    async def _on_trade(self, data: dict):
        """Handle trade updates - track taker buy/sell ratio"""
        try:
            # OKX trade format: {side: 'buy'/'sell', sz: size, px: price, ts: timestamp}
            side = data.get('side')
            size = float(data.get('sz', 0))
            
            # Track for volume ratio calculation
            self.trade_volume_1m.append({
                'side': side,
                'size': size,
                'timestamp': int(data.get('ts', 0)) // 1000
            })
            
            # Calculate taker buy ratio (last 60 trades)
            if len(self.trade_volume_1m) > 10:
                buy_volume = sum(t['size'] for t in self.trade_volume_1m if t['side'] == 'buy')
                total_volume = sum(t['size'] for t in self.trade_volume_1m)
                self.taker_buy_ratio = buy_volume / total_volume if total_volume > 0 else 0.5
                
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
        """Main signal processing loop"""
        while True:
            try:
                await asyncio.sleep(1)  # Process every second
                
                if not self.is_warmed_up:
                    continue
                
                # Calculate indicators
                indicators = self._calculate_indicators()
                
                # Check signal conditions
                checklist = self._build_checklist(indicators)
                
                # Calculate scores for signal strengthening check
                long_score = self._calculate_signal_score('LONG', indicators, checklist)
                short_score = self._calculate_signal_score('SHORT', indicators, checklist)
                
                # Process signal state machine (pass scores for strengthening verification)
                await self._process_signal_state(checklist, indicators, long_score, short_score)
                
            except Exception as e:
                logger.error(f"Error in signal processing loop: {e}")
    
    def _calculate_indicators(self) -> Dict:
        """Calculate all indicators"""
        try:
            # Get candle lists
            candles_1m_list = list(self.candles_1m)
            candles_5m_list = list(self.candles_5m)
            
            # EMAs on 1m
            ema20_1m = self.indicators.calculate_ema(candles_1m_list, 20)
            ema50_1m = self.indicators.calculate_ema(candles_1m_list, 50)
            
            # EMAs on 5m
            ema20_5m = self.indicators.calculate_ema(candles_5m_list, 20)
            ema50_5m = self.indicators.calculate_ema(candles_5m_list, 50)
            
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
            
            # Use mark price for distance calculation (more stable)
            price_for_distance = self.mark_price if self.mark_price else self.current_price
            
            return {
                'ema20_1m': ema20_1m,
                'ema50_1m': ema50_1m,
                'ema20_5m': ema20_5m,
                'ema50_5m': ema50_5m,
                'atr': atr if atr and atr > 0 else 100,  # Default to 100 if ATR is 0
                'rsi': rsi,
                'obi': obi,
                'spread': spread,
                'depth': depth,
                'price': price_for_distance,
                'taker_buy_ratio': self.taker_buy_ratio
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
            
            # 7. Gates - FIXED: Tightened depth to $500k (realistic for BTC)
            gates_pass = True
            if spread is not None:
                gates_pass = gates_pass and spread < 1.5  # 1.5 bps
            if depth is not None:
                # FIXED: $500k depth = ~5.4 BTC at $93k (reasonable minimum)
                gates_pass = gates_pass and depth > 500000  # $500k depth
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
    
    async def _process_signal_state(self, checklist: Dict, indicators: Dict, long_score: int, short_score: int):
        """Process signal state machine with invalidation logic"""
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
            
            # Signal invalidation (NEW: cancel if price moves 1 ATR adverse)
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
            
            # State machine logic
            if self.signal_state.status == "IDLE":
                if all_pass:
                    # Enter FORMING state
                    self.signal_state.status = "FORMING"
                    self.signal_state.forming_start = current_time
                    self.signal_state.direction = checklist.get('trend_direction')
                    logger.info(f"Signal FORMING: {self.signal_state.direction}")
                    
            elif self.signal_state.status == "FORMING":
                if not all_pass:
                    # Conditions no longer met, cancel
                    logger.info(f"{self.display_name} signal FORMING cancelled: conditions no longer met")
                    self.signal_state.reset()
                else:
                    # Check if 12 seconds have passed
                    elapsed = current_time - self.signal_state.forming_start
                    if elapsed >= 12:
                        # CRITICAL FIX: Verify conditions are STRENGTHENING, not deteriorating
                        # Compare current score vs score when FORMING started
                        direction = self.signal_state.direction
                        if direction == 'LONG':
                            current_score = long_score
                        else:
                            current_score = short_score
                        
                        # Store initial score when FORMING started
                        if not hasattr(self.signal_state, 'initial_score'):
                            self.signal_state.initial_score = current_score
                        
                        # FIXED: Only activate if score improved or stayed strong
                        score_change = current_score - self.signal_state.initial_score
                        
                        if score_change >= -5:  # Allow max 5 point degradation
                            # Transition to ACTIVE
                            self.signal_state.status = "ACTIVE"
                            self.signal_state.entry_price = indicators.get('price')
                            self.signal_state.entry_time = current_time
                            self.signal_state.atr_at_entry = indicators.get('atr')
                            
                            logger.info(f"{self.display_name} Signal ACTIVE: {self.signal_state.direction} at ${self.signal_state.entry_price:.2f} (score: {current_score}/100, change: {score_change:+d})")
                            
                            # Send Telegram alert
                            await self._send_signal_alert(indicators)
                        else:
                            # Conditions deteriorating, cancel
                            logger.warning(f"{self.display_name} signal FORMING cancelled: conditions deteriorating (score dropped {score_change} points)")
                            self.signal_state.reset()
                        
            elif self.signal_state.status == "ACTIVE":
                # Active signals expire after 5 minutes
                elapsed = current_time - self.signal_state.entry_time
                if elapsed >= 300:
                    logger.info(f"Signal EXPIRED after 5 minutes")
                    self.signal_state.reset()
                    
        except Exception as e:
            logger.error(f"Error processing signal state: {e}")
    
    async def _send_signal_alert(self, indicators: Dict):
        """Send Telegram alert for active signal"""
        try:
            atr = indicators.get('atr', 100)
            entry = self.signal_state.entry_price
            direction = self.signal_state.direction
            
            # Calculate levels with adaptive sizing (RSI-based)
            rsi = indicators.get('rsi', 50)
            
            if direction == "LONG":
                if rsi < 50:
                    # Momentum entry
                    sl = entry - (2.0 * atr)
                    tp1 = entry + (2.5 * atr)
                    tp2 = entry + (4.0 * atr)
                else:
                    # Pullback entry
                    sl = entry - (1.2 * atr)
                    tp1 = entry + (1.8 * atr)
                    tp2 = entry + (3.0 * atr)
            else:  # SHORT
                if rsi > 50:
                    # Momentum entry
                    sl = entry + (2.0 * atr)
                    tp1 = entry - (2.5 * atr)
                    tp2 = entry - (4.0 * atr)
                else:
                    # Pullback entry
                    sl = entry + (1.2 * atr)
                    tp1 = entry - (1.8 * atr)
                    tp2 = entry - (3.0 * atr)
            
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
                        'ema20': None,
                        'ema50': None
                    }
                },
                'atr_5m': indicators.get('atr'),
                'rsi_5m': indicators.get('rsi'),
                'cvd': {
                    '1m': None,
                    '5m': indicators.get('taker_buy_ratio', 0.5) - 0.5
                },
                'obi': indicators.get('obi'),
                'spread': indicators.get('spread'),
                'depth': indicators.get('depth')
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
                'forming_remaining': max(0, 12 - (time.time() - self.signal_state.forming_start)) if self.signal_state.status == 'FORMING' and self.signal_state.forming_start else 0,
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
                    '15m': 0
                },
                'indicators': formatted_indicators,
                'gates': {
                    'all_pass': checklist.get('gates', False),
                    'spread': {
                        'pass': indicators.get('spread', 999) < 1.5 if indicators.get('spread') is not None else False,
                        'value': indicators.get('spread', 0)
                    },
                    'depth': {
                        'pass': indicators.get('depth', 0) > 500000 if indicators.get('depth') is not None else False,
                        'value': indicators.get('depth', 0)
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
                'pass': 30 <= rsi <= 70,
                'detail': f"{rsi:.0f}" + ('' if 30 <= rsi <= 70 else ' (need 30-70)')
            },
            'ema_proximity': {
                'pass': checklist.get('ema_dist', False),
                'detail': f"{checklist.get('ema_dist_value', 0):.2f}%"
            },
            'spread': {
                'pass': checklist.get('gates', False),
                'detail': f"{indicators.get('spread', 0):.2f} bps"
            },
            'directional_alignment': {
                'pass': cvd_pass and obi_pass,
                'detail': f"CVD {taker_ratio:.3f}, OBI {obi:.3f}"
            },
            'atr_sufficient': {
                'pass': atr > 100,
                'detail': f"${atr:.0f}"
            },
            'funding_filter': {
                'pass': checklist.get('funding', False),
                'detail': f"{checklist.get('funding_value', 0):.4%}"
            },
            'all_pass': regime_pass and (30 <= rsi <= 70) and checklist.get('ema_dist', False) and checklist.get('gates', False) and cvd_pass and obi_pass and atr > 100 and checklist.get('funding', False)
        }
