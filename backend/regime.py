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
        """Detect market regime"""
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
            
            if len(candles_5m) < 2 or len(candles_15m) < 2:
                self.current_regime = RegimeType.RANGING
                return self.current_regime
            
            # Calculate EMA slopes
            prev_5m = candles_5m[-2]
            curr_5m = candles_5m[-1]
            
            # Check if we can calculate slopes
            if prev_5m.close is None or curr_5m.close is None:
                self.current_regime = RegimeType.RANGING
                return self.current_regime
            
            ema20_5m_slope = ema20_5m - prev_5m.close if prev_5m.close else 0
            
            prev_15m = candles_15m[-2]
            curr_15m = candles_15m[-1]
            
            if prev_15m.close is None or curr_15m.close is None:
                self.current_regime = RegimeType.RANGING
                return self.current_regime
                
            ema20_15m_slope = ema20_15m - prev_15m.close if prev_15m.close else 0
            
            # TRENDING_BULL: Both 5m and 15m have EMA20 > EMA50 with positive slope
            if (ema20_5m > ema50_5m and ema20_15m > ema50_15m and 
                ema20_5m_slope > 0 and ema20_15m_slope > 0):
                self.current_regime = RegimeType.TRENDING_BULL
                return self.current_regime
            
            # TRENDING_BEAR: Both 5m and 15m have EMA20 < EMA50 with negative slope
            if (ema20_5m < ema50_5m and ema20_15m < ema50_15m and 
                ema20_5m_slope < 0 and ema20_15m_slope < 0):
                self.current_regime = RegimeType.TRENDING_BEAR
                return self.current_regime
            
            # Default to RANGING
            self.current_regime = RegimeType.RANGING
            return self.current_regime
            
        except Exception as e:
            logger.error(f"Error detecting regime: {e}")
            self.current_regime = RegimeType.RANGING
            return self.current_regime
    
    def check_spread_gate(self, spread: Optional[float]) -> bool:
        """Check if spread is below 2 bps with stabilization"""
        try:
            if spread is None:
                logger.warning("Spread gate: Missing spread data")
                return self.spread_gate.current_state  # Maintain current state on missing data
            
            # Check reading
            new_reading = spread < 2.0
            return self.spread_gate.update(new_reading)
            
        except Exception as e:
            logger.error(f"Error checking spread gate: {e}")
            return self.spread_gate.current_state
    
    def check_depth_gate(self, depth: Optional[float]) -> bool:
        """Check depth gate with hysteresis and stabilization"""
        try:
            if depth is None:
                logger.warning("Depth gate: Missing depth data")
                return self.depth_gate.current_state  # Maintain current state on missing data
            
            # Hysteresis thresholds
            pass_threshold = 60000  # $60k
            fail_threshold = 40000  # $40k
            
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
    
    def get_gates_status(self, spread: Optional[float], depth: Optional[float]) -> dict:
        """Get all gates status"""
        spread_pass = self.check_spread_gate(spread)
        depth_pass = self.check_depth_gate(depth)
        
        return {
            'spread': {
                'pass': spread_pass,
                'value': spread,
                'threshold': 2.0
            },
            'depth': {
                'pass': depth_pass,
                'value': depth,
                'pass_threshold': self.depth_pass_threshold,
                'fail_threshold': self.depth_fail_threshold
            },
            'all_pass': spread_pass and depth_pass
        }
