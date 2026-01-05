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
        # V1.5 Thresholds
        self.forming_threshold = 65  # Start forming signal
        self.active_threshold = 70   # Fire signal
        
        # Hard gate limits
        self.max_ema_distance_pct = 1.0  # Must be within 1% of EMA20
        self.max_spread_bps = 5.0        # Spread must be < 5 bps
        self.min_flow_threshold = 0.08   # CVD or OBI must be > 0.08 or < -0.08
    
    def calculate_signal_score(
        self,
        direction: SignalDirection,
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
        rsi_5m: Optional[float],
        spread: Optional[float],
        gates_pass: bool
    ) -> Dict:
        """Calculate signal score using V1.5 hybrid scoring system"""
        
        score = 0
        breakdown = {}
        
        try:
            # 1. Regime Score (20 points)
            if direction == SignalDirection.LONG:
                if regime == RegimeType.TRENDING_BULL:
                    score += 20
                    breakdown['regime'] = {'points': 20, 'detail': 'TRENDING_BULL'}
                elif regime == RegimeType.RANGING and rsi_5m and rsi_5m < 30:
                    score += 12
                    breakdown['regime'] = {'points': 12, 'detail': f'RANGING + RSI {rsi_5m:.0f}'}
                else:
                    breakdown['regime'] = {'points': 0, 'detail': f'{regime}'}
            else:  # SHORT
                if regime == RegimeType.TRENDING_BEAR:
                    score += 20
                    breakdown['regime'] = {'points': 20, 'detail': 'TRENDING_BEAR'}
                elif regime == RegimeType.RANGING and rsi_5m and rsi_5m > 70:
                    score += 12
                    breakdown['regime'] = {'points': 12, 'detail': f'RANGING + RSI {rsi_5m:.0f}'}
                else:
                    breakdown['regime'] = {'points': 0, 'detail': f'{regime}'}
            
            # 2. Trend Alignment (15 points)
            aligned_count = 0
            if ema20_1m and ema50_1m:
                if direction == SignalDirection.LONG and ema20_1m > ema50_1m:
                    aligned_count += 1
                elif direction == SignalDirection.SHORT and ema20_1m < ema50_1m:
                    aligned_count += 1
            
            if ema20_5m and ema50_5m:
                if direction == SignalDirection.LONG and ema20_5m > ema50_5m:
                    aligned_count += 1
                elif direction == SignalDirection.SHORT and ema20_5m < ema50_5m:
                    aligned_count += 1
            
            if ema20_15m and ema50_15m:
                if direction == SignalDirection.LONG and ema20_15m > ema50_15m:
                    aligned_count += 1
                elif direction == SignalDirection.SHORT and ema20_15m < ema50_15m:
                    aligned_count += 1
            
            if aligned_count == 3:
                score += 15
                breakdown['trends'] = {'points': 15, 'detail': '3/3 aligned'}
            elif aligned_count == 2:
                score += 10
                breakdown['trends'] = {'points': 10, 'detail': '2/3 aligned'}
            elif aligned_count == 1:
                score += 5
                breakdown['trends'] = {'points': 5, 'detail': '1/3 aligned'}
            else:
                breakdown['trends'] = {'points': 0, 'detail': '0/3 aligned'}
            
            # 3. CVD Score (20 points)
            if cvd_5m is not None:
                abs_cvd = abs(cvd_5m)
                if abs_cvd >= 0.12:
                    score += 20
                    breakdown['cvd'] = {'points': 20, 'detail': f'{cvd_5m:.3f}'}
                elif abs_cvd >= 0.08:
                    score += 12
                    breakdown['cvd'] = {'points': 12, 'detail': f'{cvd_5m:.3f}'}
                elif abs_cvd >= 0.05:
                    score += 5
                    breakdown['cvd'] = {'points': 5, 'detail': f'{cvd_5m:.3f}'}
                else:
                    breakdown['cvd'] = {'points': 0, 'detail': f'{cvd_5m:.3f}'}
            else:
                breakdown['cvd'] = {'points': 0, 'detail': 'N/A'}
            
            # 4. OBI Score (15 points)
            if obi is not None:
                abs_obi = abs(obi)
                if abs_obi >= 0.10:
                    score += 15
                    breakdown['obi'] = {'points': 15, 'detail': f'{obi:.3f}'}
                elif abs_obi >= 0.06:
                    score += 10
                    breakdown['obi'] = {'points': 10, 'detail': f'{obi:.3f}'}
                elif abs_obi >= 0.03:
                    score += 5
                    breakdown['obi'] = {'points': 5, 'detail': f'{obi:.3f}'}
                else:
                    breakdown['obi'] = {'points': 0, 'detail': f'{obi:.3f}'}
            else:
                breakdown['obi'] = {'points': 0, 'detail': 'N/A'}
            
            # 5. RSI Zone (10 points)
            if rsi_5m is not None:
                if direction == SignalDirection.LONG:
                    if rsi_5m < 35:
                        score += 10
                        breakdown['rsi'] = {'points': 10, 'detail': f'{rsi_5m:.0f}'}
                    elif rsi_5m < 40:
                        score += 5
                        breakdown['rsi'] = {'points': 5, 'detail': f'{rsi_5m:.0f}'}
                    else:
                        breakdown['rsi'] = {'points': 0, 'detail': f'{rsi_5m:.0f}'}
                else:  # SHORT
                    if rsi_5m > 65:
                        score += 10
                        breakdown['rsi'] = {'points': 10, 'detail': f'{rsi_5m:.0f}'}
                    elif rsi_5m > 60:
                        score += 5
                        breakdown['rsi'] = {'points': 5, 'detail': f'{rsi_5m:.0f}'}
                    else:
                        breakdown['rsi'] = {'points': 0, 'detail': f'{rsi_5m:.0f}'}
            else:
                breakdown['rsi'] = {'points': 0, 'detail': 'N/A'}
            
            # 6. EMA Proximity (10 points)
            if current_price and ema20_1m:
                distance_pct = abs(current_price - ema20_1m) / ema20_1m * 100
                if distance_pct <= 0.3:
                    score += 10
                    breakdown['ema_distance'] = {'points': 10, 'detail': f'{distance_pct:.2f}%'}
                elif distance_pct <= 0.5:
                    score += 6
                    breakdown['ema_distance'] = {'points': 6, 'detail': f'{distance_pct:.2f}%'}
                elif distance_pct <= 0.8:
                    score += 3
                    breakdown['ema_distance'] = {'points': 3, 'detail': f'{distance_pct:.2f}%'}
                else:
                    breakdown['ema_distance'] = {'points': 0, 'detail': f'{distance_pct:.2f}%'}
            else:
                breakdown['ema_distance'] = {'points': 0, 'detail': 'N/A'}
            
            # 7. Gates (10 points)
            if gates_pass:
                score += 10
                breakdown['gates'] = {'points': 10, 'detail': 'PASS'}
            else:
                breakdown['gates'] = {'points': 5, 'detail': 'PARTIAL'}
            
        except Exception as e:
            logger.error(f"Error calculating signal score: {e}")
        
        return {
            'score': score,
            'breakdown': breakdown
        }
    
    def check_hard_gates(
        self,
        direction: SignalDirection,
        current_price: Optional[float],
        ema20_1m: Optional[float],
        cvd_5m: Optional[float],
        obi: Optional[float],
        spread: Optional[float]
    ) -> Dict:
        """Check mandatory hard gates"""
        
        hard_gates = {
            'ema_proximity': {'pass': False, 'detail': 'N/A'},
            'spread': {'pass': False, 'detail': 'N/A'},
            'directional_alignment': {'pass': False, 'detail': 'N/A'},
            'all_pass': False
        }
        
        try:
            # 1. EMA Proximity (< 1%)
            if current_price and ema20_1m:
                distance_pct = abs(current_price - ema20_1m) / ema20_1m * 100
                hard_gates['ema_proximity']['pass'] = distance_pct <= self.max_ema_distance_pct
                hard_gates['ema_proximity']['detail'] = f'{distance_pct:.2f}%'
            
            # 2. Spread (< 5 bps)
            if spread is not None:
                hard_gates['spread']['pass'] = spread < self.max_spread_bps
                hard_gates['spread']['detail'] = f'{spread:.2f} bps'
            
            # 3. Directional Alignment
            if cvd_5m is not None and obi is not None:
                if direction == SignalDirection.LONG:
                    # Both must be positive and at least one > 0.08
                    aligned = cvd_5m > 0 and obi > 0
                    strong = abs(cvd_5m) > self.min_flow_threshold or abs(obi) > self.min_flow_threshold
                    hard_gates['directional_alignment']['pass'] = aligned and strong
                    hard_gates['directional_alignment']['detail'] = 'Aligned' if aligned and strong else 'Not aligned'
                else:  # SHORT
                    # Both must be negative and at least one < -0.08
                    aligned = cvd_5m < 0 and obi < 0
                    strong = abs(cvd_5m) > self.min_flow_threshold or abs(obi) > self.min_flow_threshold
                    hard_gates['directional_alignment']['pass'] = aligned and strong
                    hard_gates['directional_alignment']['detail'] = 'Aligned' if aligned and strong else 'Not aligned'
            
            # Check if all hard gates pass
            hard_gates['all_pass'] = all([
                hard_gates['ema_proximity']['pass'],
                hard_gates['spread']['pass'],
                hard_gates['directional_alignment']['pass']
            ])
            
        except Exception as e:
            logger.error(f"Error checking hard gates: {e}")
        
        return hard_gates
    
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
        rsi_5m: Optional[float],
        spread: Optional[float],
        gates_pass: bool
    ) -> Dict:
        """Detect signals using V1.5 hybrid scoring system"""
        
        # Calculate scores for both directions
        long_scoring = self.calculate_signal_score(
            SignalDirection.LONG, regime,
            ema20_1m, ema50_1m, ema20_5m, ema50_5m, ema20_15m, ema50_15m,
            cvd_5m, obi, current_price, rsi_5m, spread, gates_pass
        )
        
        short_scoring = self.calculate_signal_score(
            SignalDirection.SHORT, regime,
            ema20_1m, ema50_1m, ema20_5m, ema50_5m, ema20_15m, ema50_15m,
            cvd_5m, obi, current_price, rsi_5m, spread, gates_pass
        )
        
        # Check hard gates for both directions
        long_hard_gates = self.check_hard_gates(
            SignalDirection.LONG, current_price, ema20_1m, cvd_5m, obi, spread
        )
        
        short_hard_gates = self.check_hard_gates(
            SignalDirection.SHORT, current_price, ema20_1m, cvd_5m, obi, spread
        )
        
        # Determine if signals are ready (score + hard gates)
        long_score = long_scoring['score']
        short_score = short_scoring['score']
        
        long_ready = long_score >= self.forming_threshold and long_hard_gates['all_pass']
        short_ready = short_score >= self.forming_threshold and short_hard_gates['all_pass']
        
        # Determine quality tier
        def get_quality_tier(score):
            if score >= 85:
                return 'HIGH'
            elif score >= 75:
                return 'MEDIUM'
            else:
                return 'LOW'
        
        return {
            'short': {
                'score': short_score,
                'breakdown': short_scoring['breakdown'],
                'hard_gates': short_hard_gates,
                'signal_ready': short_ready,
                'quality': get_quality_tier(short_score)
            },
            'long': {
                'score': long_score,
                'breakdown': long_scoring['breakdown'],
                'hard_gates': long_hard_gates,
                'signal_ready': long_ready,
                'quality': get_quality_tier(long_score)
            }
        }
        
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
