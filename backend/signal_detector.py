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
        self.min_atr = 100               # Minimum ATR for sufficient volatility ($100)
    
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
            
            # 3. CVD Score (20 points) - DIRECTION MATTERS
            if cvd_5m is not None:
                if direction == SignalDirection.LONG:
                    # LONG: Only positive CVD scores
                    if cvd_5m > 0.12:
                        score += 20
                        breakdown['cvd'] = {'points': 20, 'detail': f'{cvd_5m:.3f}'}
                    elif cvd_5m > 0.08:
                        score += 12
                        breakdown['cvd'] = {'points': 12, 'detail': f'{cvd_5m:.3f}'}
                    elif cvd_5m > 0.05:
                        score += 5
                        breakdown['cvd'] = {'points': 5, 'detail': f'{cvd_5m:.3f}'}
                    else:
                        breakdown['cvd'] = {'points': 0, 'detail': f'{cvd_5m:.3f}'}
                else:  # SHORT
                    # SHORT: Only negative CVD scores
                    if cvd_5m < -0.12:
                        score += 20
                        breakdown['cvd'] = {'points': 20, 'detail': f'{cvd_5m:.3f}'}
                    elif cvd_5m < -0.08:
                        score += 12
                        breakdown['cvd'] = {'points': 12, 'detail': f'{cvd_5m:.3f}'}
                    elif cvd_5m < -0.05:
                        score += 5
                        breakdown['cvd'] = {'points': 5, 'detail': f'{cvd_5m:.3f}'}
                    else:
                        breakdown['cvd'] = {'points': 0, 'detail': f'{cvd_5m:.3f}'}
            else:
                breakdown['cvd'] = {'points': 0, 'detail': 'N/A'}
            
            # 4. OBI Score (15 points) - DIRECTION MATTERS
            if obi is not None:
                if direction == SignalDirection.LONG:
                    # LONG: Only positive OBI scores
                    if obi > 0.10:
                        score += 15
                        breakdown['obi'] = {'points': 15, 'detail': f'{obi:.3f}'}
                    elif obi > 0.06:
                        score += 10
                        breakdown['obi'] = {'points': 10, 'detail': f'{obi:.3f}'}
                    elif obi > 0.03:
                        score += 5
                        breakdown['obi'] = {'points': 5, 'detail': f'{obi:.3f}'}
                    else:
                        breakdown['obi'] = {'points': 0, 'detail': f'{obi:.3f}'}
                else:  # SHORT
                    # SHORT: Only negative OBI scores
                    if obi < -0.10:
                        score += 15
                        breakdown['obi'] = {'points': 15, 'detail': f'{obi:.3f}'}
                    elif obi < -0.06:
                        score += 10
                        breakdown['obi'] = {'points': 10, 'detail': f'{obi:.3f}'}
                    elif obi < -0.03:
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

    def calculate_signal_confidence(
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
        ema20_1m: Optional[float],
        rsi_5m: Optional[float],
        spread: Optional[float],
        depth: Optional[float],
        atr_5m: Optional[float]
    ) -> Dict:
        """
        Calculate dynamic signal confidence (0-100) for quality control.
        Only signals >= 65% confidence should be activated.
        """
        
        confidence = 0
        breakdown = {}
        
        try:
            # 1. Regime alignment (5m+15m trends match): +20 points, else +10
            if ema20_5m and ema50_5m and ema20_15m and ema50_15m:
                tf_5m_aligned = (ema20_5m > ema50_5m and direction == SignalDirection.LONG) or \
                                (ema20_5m < ema50_5m and direction == SignalDirection.SHORT)
                tf_15m_aligned = (ema20_15m > ema50_15m and direction == SignalDirection.LONG) or \
                                 (ema20_15m < ema50_15m and direction == SignalDirection.SHORT)
                
                if tf_5m_aligned and tf_15m_aligned:
                    confidence += 20
                    breakdown['regime_alignment'] = {'points': 20, 'detail': '5m+15m aligned'}
                elif tf_5m_aligned or tf_15m_aligned:
                    confidence += 10
                    breakdown['regime_alignment'] = {'points': 10, 'detail': '1 timeframe aligned'}
                else:
                    breakdown['regime_alignment'] = {'points': 0, 'detail': 'No alignment'}
            else:
                breakdown['regime_alignment'] = {'points': 0, 'detail': 'N/A'}
            
            # 2. CVD magnitude: +15 if abs(cvd_5m)>0.4, +10 if >0.3, +5 if >0.2
            if cvd_5m is not None:
                abs_cvd = abs(cvd_5m)
                # Check directional alignment
                if (direction == SignalDirection.LONG and cvd_5m > 0) or \
                   (direction == SignalDirection.SHORT and cvd_5m < 0):
                    if abs_cvd > 0.4:
                        confidence += 15
                        breakdown['cvd_magnitude'] = {'points': 15, 'detail': f'{cvd_5m:.3f}'}
                    elif abs_cvd > 0.3:
                        confidence += 10
                        breakdown['cvd_magnitude'] = {'points': 10, 'detail': f'{cvd_5m:.3f}'}
                    elif abs_cvd > 0.2:
                        confidence += 5
                        breakdown['cvd_magnitude'] = {'points': 5, 'detail': f'{cvd_5m:.3f}'}
                    else:
                        breakdown['cvd_magnitude'] = {'points': 0, 'detail': f'{cvd_5m:.3f} weak'}
                else:
                    breakdown['cvd_magnitude'] = {'points': 0, 'detail': f'{cvd_5m:.3f} wrong direction'}
            else:
                breakdown['cvd_magnitude'] = {'points': 0, 'detail': 'N/A'}
            
            # 3. OBI strength: +15 if abs(obi)>0.3, +10 if >0.2, +5 if >0.15
            if obi is not None:
                abs_obi = abs(obi)
                # Check directional alignment
                if (direction == SignalDirection.LONG and obi > 0) or \
                   (direction == SignalDirection.SHORT and obi < 0):
                    if abs_obi > 0.3:
                        confidence += 15
                        breakdown['obi_strength'] = {'points': 15, 'detail': f'{obi:.3f}'}
                    elif abs_obi > 0.2:
                        confidence += 10
                        breakdown['obi_strength'] = {'points': 10, 'detail': f'{obi:.3f}'}
                    elif abs_obi > 0.15:
                        confidence += 5
                        breakdown['obi_strength'] = {'points': 5, 'detail': f'{obi:.3f}'}
                    else:
                        breakdown['obi_strength'] = {'points': 0, 'detail': f'{obi:.3f} weak'}
                else:
                    breakdown['obi_strength'] = {'points': 0, 'detail': f'{obi:.3f} wrong direction'}
            else:
                breakdown['obi_strength'] = {'points': 0, 'detail': 'N/A'}
            
            # 4. RSI position: +15 if 40-60 (neutral), +10 if 35-65, +5 if 30-70
            if rsi_5m is not None:
                if 40 <= rsi_5m <= 60:
                    confidence += 15
                    breakdown['rsi_position'] = {'points': 15, 'detail': f'{rsi_5m:.0f} (neutral zone)'}
                elif 35 <= rsi_5m <= 65:
                    confidence += 10
                    breakdown['rsi_position'] = {'points': 10, 'detail': f'{rsi_5m:.0f}'}
                elif 30 <= rsi_5m <= 70:
                    confidence += 5
                    breakdown['rsi_position'] = {'points': 5, 'detail': f'{rsi_5m:.0f}'}
                else:
                    breakdown['rsi_position'] = {'points': 0, 'detail': f'{rsi_5m:.0f} extreme'}
            else:
                breakdown['rsi_position'] = {'points': 0, 'detail': 'N/A'}
            
            # 5. EMA proximity: +15 if <0.15% from EMA20, +10 if <0.25%, +5 if <0.35%
            if current_price and ema20_1m:
                distance_pct = abs(current_price - ema20_1m) / ema20_1m * 100
                if distance_pct < 0.15:
                    confidence += 15
                    breakdown['ema_proximity'] = {'points': 15, 'detail': f'{distance_pct:.2f}%'}
                elif distance_pct < 0.25:
                    confidence += 10
                    breakdown['ema_proximity'] = {'points': 10, 'detail': f'{distance_pct:.2f}%'}
                elif distance_pct < 0.35:
                    confidence += 5
                    breakdown['ema_proximity'] = {'points': 5, 'detail': f'{distance_pct:.2f}%'}
                else:
                    breakdown['ema_proximity'] = {'points': 0, 'detail': f'{distance_pct:.2f}% too far'}
            else:
                breakdown['ema_proximity'] = {'points': 0, 'detail': 'N/A'}
            
            # 6. Gates quality: +10 if spread<1bps AND depth>$25M, +5 if spread<1.5bps AND depth>$15M
            if spread is not None and depth is not None:
                depth_millions = depth / 1_000_000
                if spread < 1.0 and depth_millions > 25:
                    confidence += 10
                    breakdown['gates_quality'] = {'points': 10, 'detail': f'{spread:.2f}bps, ${depth_millions:.0f}M'}
                elif spread < 1.5 and depth_millions > 15:
                    confidence += 5
                    breakdown['gates_quality'] = {'points': 5, 'detail': f'{spread:.2f}bps, ${depth_millions:.0f}M'}
                else:
                    breakdown['gates_quality'] = {'points': 0, 'detail': f'{spread:.2f}bps, ${depth_millions:.0f}M'}
            else:
                breakdown['gates_quality'] = {'points': 0, 'detail': 'N/A'}
            
            # 7. ATR regime: +10 if >150 (sufficient volatility for scalping)
            if atr_5m is not None:
                if atr_5m > 150:
                    confidence += 10
                    breakdown['atr_regime'] = {'points': 10, 'detail': f'${atr_5m:.0f}'}
                elif atr_5m > 100:
                    confidence += 5
                    breakdown['atr_regime'] = {'points': 5, 'detail': f'${atr_5m:.0f}'}
                else:
                    breakdown['atr_regime'] = {'points': 0, 'detail': f'${atr_5m:.0f} low volatility'}
            else:
                breakdown['atr_regime'] = {'points': 0, 'detail': 'N/A'}
            
        except Exception as e:
            logger.error(f"Error calculating signal confidence: {e}")
        
        return {
            'confidence': confidence,
            'breakdown': breakdown,
            'quality_grade': 'HIGH' if confidence >= 80 else 'MEDIUM' if confidence >= 65 else 'LOW'
        }

    
    def check_hard_gates(
        self,
        direction: SignalDirection,
        current_price: Optional[float],
        ema20_1m: Optional[float],
        cvd_5m: Optional[float],
        obi: Optional[float],
        spread: Optional[float],
        rsi_5m: Optional[float],
        regime: RegimeType,
        atr_5m: Optional[float],
        current_volume: Optional[float] = None,
        vol_ma20: Optional[float] = None
    ) -> Dict:
        """Check mandatory hard gates"""
        
        hard_gates = {
            'ema_proximity': {'pass': False, 'detail': 'N/A'},
            'spread': {'pass': False, 'detail': 'N/A'},
            'directional_alignment': {'pass': False, 'detail': 'N/A'},
            'rsi_filter': {'pass': False, 'detail': 'N/A'},
            'regime_filter': {'pass': False, 'detail': 'N/A'},
            'atr_sufficient': {'pass': False, 'detail': 'N/A'},
            'volume_surge': {'pass': False, 'detail': 'N/A'},
            'all_pass': False
        }
        
        try:
            # 1. Regime Filter (CRITICAL: Block RANGING completely)
            if regime == RegimeType.TRENDING_BULL or regime == RegimeType.TRENDING_BEAR:
                hard_gates['regime_filter']['pass'] = True
                hard_gates['regime_filter']['detail'] = str(regime)
            else:
                hard_gates['regime_filter']['pass'] = False
                hard_gates['regime_filter']['detail'] = f'{regime} (BLOCKED)'
            
            # 2. RSI Filter (30-70 range for BULL/BEAR regimes)
            if rsi_5m is not None:
                if 30 <= rsi_5m <= 70:
                    hard_gates['rsi_filter']['pass'] = True
                    hard_gates['rsi_filter']['detail'] = f'{rsi_5m:.0f}'
                else:
                    hard_gates['rsi_filter']['pass'] = False
                    hard_gates['rsi_filter']['detail'] = f'{rsi_5m:.0f} (must be 30-70)'
            
            # 3. EMA Proximity (< 1%)
            if current_price and ema20_1m:
                distance_pct = abs(current_price - ema20_1m) / ema20_1m * 100
                hard_gates['ema_proximity']['pass'] = distance_pct <= self.max_ema_distance_pct
                hard_gates['ema_proximity']['detail'] = f'{distance_pct:.2f}%'
            
            # 4. Spread (< 5 bps)
            if spread is not None:
                hard_gates['spread']['pass'] = spread < self.max_spread_bps
                hard_gates['spread']['detail'] = f'{spread:.2f} bps'
            
            # 5. Directional Alignment with HIGHER thresholds
            if cvd_5m is not None and obi is not None:
                if direction == SignalDirection.LONG:
                    # Both must be positive and strongly directional
                    cvd_strong = cvd_5m >= 0.30  # Increased from 0.15
                    obi_strong = obi >= 0.20      # Increased from 0.12
                    hard_gates['directional_alignment']['pass'] = cvd_strong and obi_strong
                    hard_gates['directional_alignment']['detail'] = f'CVD {cvd_5m:.3f}, OBI {obi:.3f}' + (' ✓' if (cvd_strong and obi_strong) else ' ✗')
                else:  # SHORT
                    # Both must be negative and strongly directional
                    cvd_strong = cvd_5m <= -0.30  # Increased from -0.15
                    obi_strong = obi <= -0.20     # Increased from -0.12
                    hard_gates['directional_alignment']['pass'] = cvd_strong and obi_strong
                    hard_gates['directional_alignment']['detail'] = f'CVD {cvd_5m:.3f}, OBI {obi:.3f}' + (' ✓' if (cvd_strong and obi_strong) else ' ✗')
            
            # 6. ATR Minimum (> $100 for sufficient volatility)
            if atr_5m is not None:
                hard_gates['atr_sufficient']['pass'] = atr_5m > self.min_atr
                hard_gates['atr_sufficient']['detail'] = f'${atr_5m:.0f}' + (' ✓' if atr_5m > self.min_atr else f' (need >${self.min_atr})')
            
            # 7. Volume Surge (> 1.3x vol_ma20 to avoid illiquid periods)
            if current_volume is not None and vol_ma20 is not None and vol_ma20 > 0:
                vol_ratio = current_volume / vol_ma20
                hard_gates['volume_surge']['pass'] = vol_ratio > 1.3
                hard_gates['volume_surge']['detail'] = f'{vol_ratio:.2f}x' + (' ✓' if vol_ratio > 1.3 else ' (need >1.3x)')
            
            # Check if all hard gates pass
            hard_gates['all_pass'] = all([
                hard_gates['regime_filter']['pass'],
                hard_gates['rsi_filter']['pass'],
                hard_gates['ema_proximity']['pass'],
                hard_gates['spread']['pass'],
                hard_gates['directional_alignment']['pass'],
                hard_gates['atr_sufficient']['pass'],
                hard_gates['volume_surge']['pass']
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
        gates_pass: bool,
        atr_5m: Optional[float],
        depth: Optional[float],
        current_volume: Optional[float] = None,
        vol_ma20: Optional[float] = None
    ) -> Dict:
        """Detect signals using V1.5 hybrid scoring system with strict quality filters"""
        
        # Check hard gates for both directions (always evaluate for diagnostics)
        long_hard_gates = self.check_hard_gates(
            SignalDirection.LONG, current_price, ema20_1m, cvd_5m, obi, spread, rsi_5m, regime, atr_5m, current_volume, vol_ma20
        )
        
        short_hard_gates = self.check_hard_gates(
            SignalDirection.SHORT, current_price, ema20_1m, cvd_5m, obi, spread, rsi_5m, regime, atr_5m, current_volume, vol_ma20
        )
        
        # CRITICAL: Block all RANGING regime signals (but show diagnostic info)
        if regime == RegimeType.RANGING or regime == RegimeType.CHAOTIC:
            return {
                'short': {
                    'score': 0,
                    'breakdown': {'regime': {'points': 0, 'detail': f'{regime} (BLOCKED)'}},
                    'hard_gates': short_hard_gates,
                    'signal_ready': False,
                    'quality': 'BLOCKED',
                    'confidence': 0
                },
                'long': {
                    'score': 0,
                    'breakdown': {'regime': {'points': 0, 'detail': f'{regime} (BLOCKED)'}},
                    'hard_gates': long_hard_gates,
                    'signal_ready': False,
                    'quality': 'BLOCKED',
                    'confidence': 0
                }
            }
        
        # Calculate scores for both directions (only for TRENDING regimes)
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
        
        # Check hard gates with STRICTER thresholds for both directions (including ATR and volume)
        long_hard_gates = self.check_hard_gates(
            SignalDirection.LONG, current_price, ema20_1m, cvd_5m, obi, spread, rsi_5m, regime, atr_5m, current_volume, vol_ma20
        )
        
        short_hard_gates = self.check_hard_gates(
            SignalDirection.SHORT, current_price, ema20_1m, cvd_5m, obi, spread, rsi_5m, regime, atr_5m, current_volume, vol_ma20
        )
        
        # Calculate dynamic confidence for both directions
        long_confidence_result = self.calculate_signal_confidence(
            SignalDirection.LONG, regime,
            ema20_5m, ema50_5m, ema20_15m, ema50_15m,
            cvd_5m, obi, current_price, ema20_1m, rsi_5m,
            spread, depth, atr_5m
        )
        
        short_confidence_result = self.calculate_signal_confidence(
            SignalDirection.SHORT, regime,
            ema20_5m, ema50_5m, ema20_15m, ema50_15m,
            cvd_5m, obi, current_price, ema20_1m, rsi_5m,
            spread, depth, atr_5m
        )
        
        # Determine if signals are ready (score + hard gates + confidence >= 65)
        long_score = long_scoring['score']
        short_score = short_scoring['score']
        long_confidence = long_confidence_result['confidence']
        short_confidence = short_confidence_result['confidence']
        
        # Signal ready requires: score >= threshold, all hard gates pass, AND confidence >= 65
        long_ready = (long_score >= self.forming_threshold and 
                     long_hard_gates['all_pass'] and 
                     long_confidence >= 65)
        short_ready = (short_score >= self.forming_threshold and 
                      short_hard_gates['all_pass'] and 
                      short_confidence >= 65)
        
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
                'quality': get_quality_tier(short_score),
                'confidence': short_confidence,
                'confidence_breakdown': short_confidence_result['breakdown'],
                'quality_grade': short_confidence_result['quality_grade']
            },
            'long': {
                'score': long_score,
                'breakdown': long_scoring['breakdown'],
                'hard_gates': long_hard_gates,
                'signal_ready': long_ready,
                'quality': get_quality_tier(long_score),
                'confidence': long_confidence,
                'confidence_breakdown': long_confidence_result['breakdown'],
                'quality_grade': long_confidence_result['quality_grade']
            }
        }
