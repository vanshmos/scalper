import logging
from typing import Optional, Dict
from regime import RegimeType
from enum import Enum

logger = logging.getLogger(__name__)

class SignalDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"

class SignalDetector:
    def __init__(self):
        self.min_confidence = 70
        
    def check_signal_checklist(
        self,
        direction: SignalDirection,
        regime: RegimeType,
        ema20_5m: Optional[float],
        ema50_5m: Optional[float],
        ema20_15m: Optional[float],
        ema50_15m: Optional[float],
        cvd_5m: Optional[float],
        obi: Optional[float],
        current_price: Optional[float],
        ema20_1m: Optional[float]
    ) -> Dict:
        """Check signal checklist conditions"""
        checklist = {
            'regime': {'pass': False, 'description': ''},
            'structure': {'pass': False, 'description': ''},
            'cvd': {'pass': False, 'description': ''},
            'obi': {'pass': False, 'description': ''},
            'pullback': {'pass': False, 'description': ''},
            'all_pass': False
        }
        
        try:
            # Calculate actual market structure (same for both directions)
            structure_5m_state = "NEUTRAL"
            structure_15m_state = "NEUTRAL"
            
            if ema20_5m and ema50_5m:
                structure_5m_state = "BULL" if ema20_5m > ema50_5m else "BEAR"
            
            if ema20_15m and ema50_15m:
                structure_15m_state = "BULL" if ema20_15m > ema50_15m else "BEAR"
            
            if direction == SignalDirection.SHORT:
                # SHORT checklist
                # 1. Regime is TRENDING_BEAR
                checklist['regime']['pass'] = regime == RegimeType.TRENDING_BEAR
                checklist['regime']['description'] = f"Regime: {regime}"
                
                # 2. Structure: 5m BEAR and 15m BEAR (show actual structure)
                if ema20_5m and ema50_5m and ema20_15m and ema50_15m:
                    structure_5m_bear = ema20_5m < ema50_5m
                    structure_15m_bear = ema20_15m < ema50_15m
                    checklist['structure']['pass'] = structure_5m_bear and structure_15m_bear
                    checklist['structure']['description'] = f"5m: {structure_5m_state}, 15m: {structure_15m_state}"
                
                # 3. CVD 5m below -0.15
                if cvd_5m is not None:
                    checklist['cvd']['pass'] = cvd_5m < -0.15
                    checklist['cvd']['description'] = f"CVD 5m: {cvd_5m:.3f} (need < -0.15)"
                
                # 4. OBI below -0.12
                if obi is not None:
                    checklist['obi']['pass'] = obi < -0.12
                    checklist['obi']['description'] = f"OBI: {obi:.3f} (need < -0.12)"
                
                # 5. Price within 0.5% of EMA20 on 1m
                if current_price and ema20_1m:
                    distance_pct = abs(current_price - ema20_1m) / ema20_1m * 100
                    checklist['pullback']['pass'] = distance_pct <= 0.5
                    checklist['pullback']['description'] = f"Distance from EMA20: {distance_pct:.2f}% (need ≤ 0.5%)"
                
            elif direction == SignalDirection.LONG:
                # LONG checklist
                # 1. Regime is TRENDING_BULL
                checklist['regime']['pass'] = regime == RegimeType.TRENDING_BULL
                checklist['regime']['description'] = f"Regime: {regime}"
                
                # 2. Structure: 5m BULL and 15m BULL (show actual structure)
                if ema20_5m and ema50_5m and ema20_15m and ema50_15m:
                    structure_5m_bull = ema20_5m > ema50_5m
                    structure_15m_bull = ema20_15m > ema50_15m
                    checklist['structure']['pass'] = structure_5m_bull and structure_15m_bull
                    checklist['structure']['description'] = f"5m: {structure_5m_state}, 15m: {structure_15m_state}"
                
                # 3. CVD 5m above 0.15
                if cvd_5m is not None:
                    checklist['cvd']['pass'] = cvd_5m > 0.15
                    checklist['cvd']['description'] = f"CVD 5m: {cvd_5m:.3f} (need > 0.15)"
                
                # 4. OBI above 0.12
                if obi is not None:
                    checklist['obi']['pass'] = obi > 0.12
                    checklist['obi']['description'] = f"OBI: {obi:.3f} (need > 0.12)"
                
                # 5. Price within 0.5% of EMA20 on 1m
                if current_price and ema20_1m:
                    distance_pct = abs(current_price - ema20_1m) / ema20_1m * 100
                    checklist['pullback']['pass'] = distance_pct <= 0.5
                    checklist['pullback']['description'] = f"Distance from EMA20: {distance_pct:.2f}% (need ≤ 0.5%)"
            
            # Check if all conditions pass
            checklist['all_pass'] = all([
                checklist['regime']['pass'],
                checklist['structure']['pass'],
                checklist['cvd']['pass'],
                checklist['obi']['pass'],
                checklist['pullback']['pass']
            ])
            
        except Exception as e:
            logger.error(f"Error checking signal checklist: {e}")
        
        return checklist
    
    def calculate_confidence(
        self,
        direction: SignalDirection,
        checklist: Dict,
        cvd_5m: Optional[float],
        obi: Optional[float],
        current_price: Optional[float],
        ema20_1m: Optional[float],
        rsi_5m: Optional[float]
    ) -> int:
        """Calculate confidence score 0-100"""
        score = 0
        
        try:
            # Structure aligned: 30 points
            if checklist['structure']['pass']:
                score += 30
            
            # CVD strength: 25 points (scaled by how far past threshold)
            if cvd_5m is not None:
                if direction == SignalDirection.SHORT:
                    if cvd_5m < -0.15:
                        # Scale: -0.15 = full points, -0.30 or below = 25 points
                        cvd_strength = min(abs(cvd_5m + 0.15) / 0.15, 1.0)
                        score += int(25 * cvd_strength)
                elif direction == SignalDirection.LONG:
                    if cvd_5m > 0.15:
                        cvd_strength = min((cvd_5m - 0.15) / 0.15, 1.0)
                        score += int(25 * cvd_strength)
            
            # OBI strength: 20 points (scaled by how far past threshold)
            if obi is not None:
                if direction == SignalDirection.SHORT:
                    if obi < -0.12:
                        obi_strength = min(abs(obi + 0.12) / 0.12, 1.0)
                        score += int(20 * obi_strength)
                elif direction == SignalDirection.LONG:
                    if obi > 0.12:
                        obi_strength = min((obi - 0.12) / 0.12, 1.0)
                        score += int(20 * obi_strength)
            
            # Pullback quality: 20 points (closer to EMA20 = better)
            if current_price and ema20_1m:
                distance_pct = abs(current_price - ema20_1m) / ema20_1m * 100
                if distance_pct <= 0.5:
                    # Perfect at 0%, decreases linearly to 0% at 0.5%
                    pullback_quality = 1.0 - (distance_pct / 0.5)
                    score += int(20 * pullback_quality)
            
            # Funding context: 5 points (placeholder - no funding rate in current data)
            # Could add later if funding rate is available
            score += 5
            
            # RSI penalty: subtract 15 if extreme RSI
            if rsi_5m is not None:
                if direction == SignalDirection.SHORT and rsi_5m < 25:
                    score -= 15
                elif direction == SignalDirection.LONG and rsi_5m > 75:
                    score -= 15
            
            # Clamp score to 0-100
            score = max(0, min(100, score))
            
        except Exception as e:
            logger.error(f"Error calculating confidence: {e}")
            score = 0
        
        return score
    
    def detect_signal(
        self,
        regime: RegimeType,
        ema20_1m: Optional[float],
        ema50_1m: Optional[float],
        ema20_5m: Optional[float],
        ema50_5m: Optional[float],
        ema20_15m: Optional[float],
        ema50_15m: Optional[float],
        cvd_5m: Optional[float],
        obi: Optional[float],
        current_price: Optional[float],
        rsi_5m: Optional[float]
    ) -> Dict:
        """Detect if signal conditions are met"""
        
        # Check both directions
        short_checklist = self.check_signal_checklist(
            SignalDirection.SHORT, regime,
            ema20_5m, ema50_5m, ema20_15m, ema50_15m,
            cvd_5m, obi, current_price, ema20_1m
        )
        
        long_checklist = self.check_signal_checklist(
            SignalDirection.LONG, regime,
            ema20_5m, ema50_5m, ema20_15m, ema50_15m,
            cvd_5m, obi, current_price, ema20_1m
        )
        
        # Calculate confidence for each direction
        short_confidence = self.calculate_confidence(
            SignalDirection.SHORT, short_checklist,
            cvd_5m, obi, current_price, ema20_1m, rsi_5m
        )
        
        long_confidence = self.calculate_confidence(
            SignalDirection.LONG, long_checklist,
            cvd_5m, obi, current_price, ema20_1m, rsi_5m
        )
        
        return {
            'short': {
                'checklist': short_checklist,
                'confidence': short_confidence,
                'signal_ready': short_checklist['all_pass'] and short_confidence >= self.min_confidence
            },
            'long': {
                'checklist': long_checklist,
                'confidence': long_confidence,
                'signal_ready': long_checklist['all_pass'] and long_confidence >= self.min_confidence
            }
        }
