import logging
from typing import Optional, List
from candle_builder import Candle
from enum import Enum

logger = logging.getLogger(__name__)

class RegimeType(str, Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGING = "RANGING"
    CHAOTIC = "CHAOTIC"

class RegimeDetector:
    def __init__(self):
        self.current_regime = RegimeType.RANGING
        self.atr_baseline: Optional[float] = None
        self.atr_baseline_samples = []
        self.atr_baseline_period = 100  # Build baseline from 100 samples
        
        # Hysteresis for gates
        self.depth_passing = False
        self.depth_pass_threshold = 60000  # $60k
        self.depth_fail_threshold = 40000  # $40k
        
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
        """Check if spread is below 2 bps"""
        try:
            if spread is None:
                return False
            return spread < 2.0
        except Exception as e:
            logger.error(f"Error checking spread gate: {e}")
            return False
    
    def check_depth_gate(self, depth: Optional[float]) -> bool:
        """Check depth gate with hysteresis"""
        try:
            if depth is None:
                return self.depth_passing
            
            # Hysteresis logic
            if depth > self.depth_pass_threshold:
                self.depth_passing = True
            elif depth < self.depth_fail_threshold:
                self.depth_passing = False
            # Between thresholds: maintain current state
            
            return self.depth_passing
            
        except Exception as e:
            logger.error(f"Error checking depth gate: {e}")
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
