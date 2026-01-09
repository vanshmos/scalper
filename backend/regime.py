import logging
import time
from typing import Optional, List
from candle_builder import Candle
from enum import Enum

logger = logging.getLogger(__name__)

class RegimeType(str, Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGING = "RANGING"
    CHAOTIC = "CHAOTIC"

class GateState:
    """Track gate state with stabilization"""
    def __init__(self, name: str, stability_threshold: int = 3):
        self.name = name
        self.current_state = False
        self.pending_state = None
        self.pending_count = 0
        self.stability_threshold = stability_threshold  # Require 3 consecutive readings
        self.last_change_time = 0
        self.last_log_time = 0
        
    def update(self, new_reading: bool) -> bool:
        """Update gate state with stabilization logic"""
        # If reading matches current state, reset pending
        if new_reading == self.current_state:
            if self.pending_state is not None:
                self.pending_state = None
                self.pending_count = 0
            return self.current_state
        
        # If reading differs from current state
        if self.pending_state == new_reading:
            # Same pending state, increment counter
            self.pending_count += 1
        else:
            # New pending state, reset counter
            self.pending_state = new_reading
            self.pending_count = 1
        
        # Check if we've reached threshold
        if self.pending_count >= self.stability_threshold:
            # Change state
            old_state = self.current_state
            self.current_state = new_reading
            self.pending_state = None
            self.pending_count = 0
            self.last_change_time = time.time()
            
            # Log state change (throttled to once per 10 seconds)
            current_time = time.time()
            if current_time - self.last_log_time >= 10:
                logger.info(f"Gate '{self.name}' changed: {old_state} → {new_reading}")
                self.last_log_time = current_time
        
        return self.current_state

class RegimeDetector:
    def __init__(self):
        self.current_regime = RegimeType.RANGING
        self.atr_baseline: Optional[float] = None
        self.atr_baseline_samples = []
        self.atr_baseline_period = 100  # Build baseline from 100 samples
        
        # Gate state trackers with stabilization
        self.spread_gate = GateState("spread", stability_threshold=3)
        self.depth_gate = GateState("depth", stability_threshold=3)
        
        # Data staleness tracking
        self.last_orderbook_time = 0
        self.data_staleness_threshold = 10  # 10 seconds
        
    def _calculate_ema(self, candles: List[Candle], period: int) -> Optional[float]:
        """Calculate EMA for a list of candles"""
        if len(candles) < period:
            return None
        
        closes = [c.close for c in candles if c.close is not None]
        if len(closes) < period:
            return None
        
        multiplier = 2 / (period + 1)
        ema = sum(closes[:period]) / period  # Start with SMA
        
        for close in closes[period:]:
            ema = (close * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def detect_regime(
        self,
        candles_5m: List[Candle],
        candles_15m: List[Candle],
        ema20_5m: Optional[float],
        ema50_5m: Optional[float],
        ema20_15m: Optional[float],
        ema50_15m: Optional[float],
        atr_5m: Optional[float]
    ) -> RegimeType:
        """
        Detect market regime using TRUE SLOPE calculation.
        
        FIXED: Previous implementation used (ema - prev_candle.close) which is mathematically flawed.
        NEW: Calculate prev_ema using history minus last candle, then slope = current_ema - prev_ema
        
        Trend confirmed only if: EMA alignment AND slope matches direction
        """
        try:
            # Update ATR baseline
            if atr_5m is not None:
                self.atr_baseline_samples.append(atr_5m)
                if len(self.atr_baseline_samples) > self.atr_baseline_period:
                    self.atr_baseline_samples.pop(0)
                self.atr_baseline = sum(self.atr_baseline_samples) / len(self.atr_baseline_samples)
            
            # Check for CHAOTIC regime first
            if atr_5m and self.atr_baseline:
                if atr_5m > 2 * self.atr_baseline:
                    self.current_regime = RegimeType.CHAOTIC
                    return self.current_regime
            
            # Check if we have enough data for EMAs
            if not all([ema20_5m, ema50_5m, ema20_15m, ema50_15m]):
                self.current_regime = RegimeType.RANGING
                return self.current_regime
            
            # Need at least 22 candles to calculate prev EMA20
            if len(candles_5m) < 22 or len(candles_15m) < 22:
                self.current_regime = RegimeType.RANGING
                return self.current_regime
            
            # FIXED: Calculate TRUE SLOPE using previous EMA
            # Previous EMA = EMA calculated on candles[:-1] (excluding last candle)
            prev_ema20_5m = self._calculate_ema(candles_5m[:-1], 20)
            prev_ema20_15m = self._calculate_ema(candles_15m[:-1], 20)
            
            if prev_ema20_5m is None or prev_ema20_15m is None:
                self.current_regime = RegimeType.RANGING
                return self.current_regime
            
            # TRUE SLOPE = current_ema - prev_ema
            ema20_5m_slope = ema20_5m - prev_ema20_5m
            ema20_15m_slope = ema20_15m - prev_ema20_15m
            
            # TRENDING_BULL: EMA20 > EMA50 AND positive slope (trend direction matches alignment)
            if (ema20_5m > ema50_5m and ema20_15m > ema50_15m and 
                ema20_5m_slope > 0 and ema20_15m_slope > 0):
                self.current_regime = RegimeType.TRENDING_BULL
                return self.current_regime
            
            # TRENDING_BEAR: EMA20 < EMA50 AND negative slope (trend direction matches alignment)
            if (ema20_5m < ema50_5m and ema20_15m < ema50_15m and 
                ema20_5m_slope < 0 and ema20_15m_slope < 0):
                self.current_regime = RegimeType.TRENDING_BEAR
                return self.current_regime
            
            # Default to RANGING (EMA alignment doesn't match slope = choppy/transitioning)
            self.current_regime = RegimeType.RANGING
            return self.current_regime
            
        except Exception as e:
            logger.error(f"Error detecting regime: {e}")
            self.current_regime = RegimeType.RANGING
            return self.current_regime
    
    def check_spread_gate(self, spread: Optional[float], threshold: Optional[float] = None) -> bool:
        """
        Check if spread is below threshold with stabilization
        
        Args:
            spread: Current spread in basis points
            threshold: Optional dynamic threshold (defaults to 2.5 bps)
        """
        try:
            if spread is None:
                # Maintain current state on missing data
                return self.spread_gate.current_state
            
            # Use dynamic threshold if provided, otherwise use default
            pass_threshold = threshold if threshold is not None else 2.5
            fail_threshold = pass_threshold * 1.6  # Hysteresis: 60% above pass
            
            # Determine raw reading based on hysteresis
            if spread < pass_threshold:
                new_reading = True
            elif spread > fail_threshold:
                new_reading = False
            else:
                # In hysteresis zone - maintain current state
                return self.spread_gate.current_state
            
            return self.spread_gate.update(new_reading)
            
        except Exception as e:
            logger.error(f"Error checking spread gate: {e}")
            return self.spread_gate.current_state
    
    def check_depth_gate(self, depth: Optional[float], threshold: Optional[float] = None) -> bool:
        """
        Check depth gate with hysteresis and stabilization
        
        Args:
            depth: Current orderbook depth in USD
            threshold: Optional dynamic threshold (defaults to $30k)
        """
        try:
            if depth is None:
                # Maintain current state on missing data
                return self.depth_gate.current_state
            
            # Use dynamic threshold if provided, otherwise use default
            pass_threshold = threshold if threshold is not None else 30000
            fail_threshold = pass_threshold * 0.67  # Hysteresis: 33% below pass
            
            # Determine raw reading based on hysteresis
            if depth > pass_threshold:
                new_reading = True
            elif depth < fail_threshold:
                new_reading = False
            else:
                # In hysteresis zone - maintain current state
                return self.depth_gate.current_state
            
            return self.depth_gate.update(new_reading)
            
        except Exception as e:
            logger.error(f"Error checking depth gate: {e}")
            return self.depth_gate.current_state
    
    def check_data_staleness(self, orderbook_timestamp: Optional[float] = None) -> bool:
        """Check if orderbook data is stale"""
        if orderbook_timestamp:
            self.last_orderbook_time = orderbook_timestamp
        
        if self.last_orderbook_time == 0:
            return False  # No data received yet
        
        age = time.time() - self.last_orderbook_time
        if age > self.data_staleness_threshold:
            logger.warning(f"Orderbook data is stale: {age:.1f}s old")
            return True
        
        return False
    
    def get_gates_status(self, spread: Optional[float], depth: Optional[float], orderbook_timestamp: Optional[float] = None) -> dict:
        """Get all gates status with health monitoring"""
        # Check data staleness
        is_stale = self.check_data_staleness(orderbook_timestamp)
        
        # If data is stale, maintain current gate states
        if is_stale:
            spread_pass = self.spread_gate.current_state
            depth_pass = self.depth_gate.current_state
        else:
            spread_pass = self.check_spread_gate(spread)
            depth_pass = self.check_depth_gate(depth)
        
        return {
            'spread': {
                'pass': spread_pass,
                'value': spread,
                'threshold': 2.0,
                'pending': self.spread_gate.pending_count if self.spread_gate.pending_state is not None else 0
            },
            'depth': {
                'pass': depth_pass,
                'value': depth,
                'pass_threshold': 60000,
                'fail_threshold': 40000,
                'pending': self.depth_gate.pending_count if self.depth_gate.pending_state is not None else 0
            },
            'all_pass': spread_pass and depth_pass,
            'data_stale': is_stale
        }
