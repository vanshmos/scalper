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

class BTCSignalEngine:
    """BTC-only signal engine using OKX candle channels"""
    
    def __init__(self, symbol: str = "BTC-USDT-SWAP"):
        self.symbol = symbol
        self.rest_client = OKXRestClient()
        self.ws_client = OKXWebSocketClient(symbol)
        self.indicators = Indicators()
        self.alert_manager = AlertManager()
        
        # Candle storage (using deque for efficient operations)
        self.candles_1m = deque(maxlen=200)  # Keep last 200 1m candles
        self.candles_5m = deque(maxlen=100)  # Keep last 100 5m candles
        
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
        logger.info(f"Starting BTC signal engine for {self.symbol}...")
        
        # 1. Backfill historical data
        await self._backfill_candles()
        
        # 2. Fetch initial funding rate
        await self._fetch_funding_rate()
        
        # 3. Setup WebSocket callbacks
        self.ws_client.on_candle_1m = self._on_candle_1m
        self.ws_client.on_candle_5m = self._on_candle_5m
        self.ws_client.on_ticker = self._on_ticker
        self.ws_client.on_orderbook = self._on_orderbook
        self.ws_client.on_trade = self._on_trade
        self.ws_client.on_funding_rate = self._on_funding_rate
        self.ws_client.on_mark_price = self._on_mark_price
        
        # 4. Start WebSocket connection
        asyncio.create_task(self.ws_client.start())
        
        # 5. Start signal processing loop
        asyncio.create_task(self._signal_processing_loop())
        
        logger.info("BTC signal engine started successfully")
    
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
            candle = Candle(data)
            
            # Only add confirmed candles to avoid duplicates
            if candle.confirm == '1':
                # Check if this candle already exists (by timestamp)
                if not self.candles_1m or self.candles_1m[-1].timestamp != candle.timestamp:
                    self.candles_1m.append(candle)
                    
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
            candle = Candle(data)
            
            # Only add confirmed candles
            if candle.confirm == '1':
                if not self.candles_5m or self.candles_5m[-1].timestamp != candle.timestamp:
                    self.candles_5m.append(candle)
                    
        except Exception as e:
            logger.error(f"Error handling 5m candle: {e}")
    
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
                
                # Process signal state machine
                await self._process_signal_state(checklist, indicators)
                
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
        """Build signal checklist with all 6 critical fixes"""
        try:
            checklist = {
                'regime': False,
                'trend_align': False,  # NEW: Multi-TF alignment
                'cvd': False,
                'obi': False,
                'ema_dist': False,
                'funding': False,  # NEW: Funding filter
                'gates': False
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
            
            # 1. Regime (5m trend)
            if ema20_5m and ema50_5m:
                is_bull_5m = ema20_5m > ema50_5m
                is_bear_5m = ema20_5m < ema50_5m
                checklist['regime'] = is_bull_5m or is_bear_5m
                checklist['regime_direction'] = 'BULL' if is_bull_5m else 'BEAR' if is_bear_5m else 'RANGING'
            
            # 2. Multi-TF alignment (NEW: 1m AND 5m must agree)
            if ema20_1m and ema50_1m and ema20_5m and ema50_5m:
                trend_1m = 'BULL' if ema20_1m > ema50_1m else 'BEAR'
                trend_5m = 'BULL' if ema20_5m > ema50_5m else 'BEAR'
                checklist['trend_align'] = trend_1m == trend_5m
                checklist['trend_direction'] = trend_1m if checklist['trend_align'] else 'DIVERGENT'
            
            # 3. CVD (using taker buy ratio as proxy)
            # taker_buy_ratio > 0.57 = bullish, < 0.43 = bearish
            if checklist.get('regime_direction') == 'BULL':
                checklist['cvd'] = self.taker_buy_ratio > 0.57
            elif checklist.get('regime_direction') == 'BEAR':
                checklist['cvd'] = self.taker_buy_ratio < 0.43
            
            # 4. OBI
            if obi is not None:
                if checklist.get('regime_direction') == 'BULL':
                    checklist['obi'] = obi > 0.12
                elif checklist.get('regime_direction') == 'BEAR':
                    checklist['obi'] = obi < -0.12
            
            # 5. EMA distance (WIDENED to 0.5% from 0.3%)
            if price and ema20_5m:
                distance_pct = abs(price - ema20_5m) / ema20_5m * 100
                checklist['ema_dist'] = distance_pct < 0.5  # WIDENED threshold
                checklist['ema_dist_value'] = distance_pct
            
            # 6. Funding filter (NEW: block when |funding| > 0.03%)
            if self.funding_rate is not None:
                abs_funding = abs(self.funding_rate)
                checklist['funding'] = abs_funding < 0.0003  # 0.03% = 0.0003
                checklist['funding_value'] = self.funding_rate
            
            # 7. Gates (existing)
            gates_pass = True
            if spread is not None:
                gates_pass = gates_pass and spread < 0.0015  # 1.5 bps = 0.0015
            if depth is not None:
                gates_pass = gates_pass and depth > 50000  # $50k depth
            checklist['gates'] = gates_pass
            checklist['spread_value'] = spread
            checklist['depth_value'] = depth
            
            return checklist
            
        except Exception as e:
            logger.error(f"Error building checklist: {e}")
            return {}
    
    async def _process_signal_state(self, checklist: Dict, indicators: Dict):
        """Process signal state machine with invalidation logic"""
        try:
            # Check if all checklist items pass
            all_pass = all([
                checklist.get('regime', False),
                checklist.get('trend_align', False),
                checklist.get('cvd', False),
                checklist.get('obi', False),
                checklist.get('ema_dist', False),
                checklist.get('funding', False),
                checklist.get('gates', False)
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
                    logger.info(f"Signal FORMING cancelled: conditions no longer met")
                    self.signal_state.reset()
                else:
                    # Check if 12 seconds have passed
                    elapsed = current_time - self.signal_state.forming_start
                    if elapsed >= 12:
                        # Transition to ACTIVE
                        self.signal_state.status = "ACTIVE"
                        self.signal_state.entry_price = indicators.get('price')
                        self.signal_state.entry_time = current_time
                        self.signal_state.atr_at_entry = indicators.get('atr')
                        
                        logger.info(f"Signal ACTIVE: {self.signal_state.direction} at ${self.signal_state.entry_price:.2f}")
                        
                        # Send Telegram alert
                        await self._send_signal_alert(indicators)
                        
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
                symbol=self.symbol
            )
            
        except Exception as e:
            logger.error(f"Error sending signal alert: {e}")
    
    def get_status(self) -> Dict:
        """Get current engine status for WebSocket broadcast"""
        try:
            indicators = self._calculate_indicators()
            checklist = self._build_checklist(indicators)
            
            return {
                'symbol': self.symbol,
                'connected': True,
                'is_warmed_up': self.is_warmed_up,
                'current_price': self.current_price,
                'mark_price': self.mark_price,
                'candle_counts': {
                    '1m': len(self.candles_1m),
                    '5m': len(self.candles_5m)
                },
                'indicators': indicators,
                'checklist': checklist,
                'signal_state': {
                    'status': self.signal_state.status,
                    'direction': self.signal_state.direction,
                    'entry_price': self.signal_state.entry_price,
                    'entry_time': self.signal_state.entry_time
                },
                'health': self.ws_client.get_health_status()
            }
            
        except Exception as e:
            logger.error(f"Error getting status: {e}")
            return {'error': str(e)}
