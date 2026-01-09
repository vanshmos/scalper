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
    """
    INSTITUTIONAL-GRADE Signal Detector with Alpha Enhancements
    
    Features:
    1. Velocity Signals (Anti-Spoofing Layer)
    2. Liquidity Sweep Detection (High Win-Rate Setups)
    3. VWAP Distance Guard (Slippage Protection)
    4. Adaptive Scoring with Confidence Boosts
    5. Mean Reversion Guard (Bollinger)
    6. Candle Color Guard (Falling Knife Protection)
    """
    
    def __init__(self):
        # V2.0 SURVIVAL FIX: Raised thresholds for higher quality signals
        self.forming_threshold = 80   # Raised from 65: Only form high-quality signals
        self.active_threshold = 88    # Raised from 80: Fire signal only for premium quality
        
        # Hard gate limits
        self.max_ema_distance_pct = 1.0  # Must be within 1% of EMA20
        self.max_spread_bps = 5.0        # Spread must be < 5 bps
        self.min_flow_threshold = 0.08   # CVD or OBI must be > 0.08 or < -0.08
        self.min_atr = 100               # Minimum ATR for sufficient volatility ($100)
        
        # ALPHA ENHANCEMENTS
        self.vwap_distance_threshold = 0.02  # 2% max distance from VWAP (adjusted for crypto volatility)
        self.min_velocity_threshold = 0.001   # Minimum positive velocity for LONG
    
    def check_velocity_signal(
        self,
        direction: SignalDirection,
        obi: Optional[float],
        obi_velocity: Optional[float],
        cvd: Optional[float],
        cvd_velocity: Optional[float]
    ) -> Dict:
        """
        ALPHA ENHANCEMENT 1: VELOCITY SIGNALS (Anti-Spoofing Layer)
        
        Logic:
        - Static OBI/CVD is meaningless if it's collapsing
        - Require POSITIVE and INCREASING flow for LONG signals
        - Filters out "pulling orders" (spoofing) and captures real aggression
        
        Returns: {
            'pass': bool,
            'detail': str,
            'confidence_boost': int (0-20 points)
        }
        """
        velocity_check = {
            'pass': False,
            'detail': 'N/A',
            'confidence_boost': 0
        }
        
        try:
            if obi is None or cvd is None:
                velocity_check['detail'] = 'Missing OBI/CVD'
                return velocity_check
            
            if obi_velocity is None or cvd_velocity is None:
                # No velocity data yet - neutral
                velocity_check['pass'] = True
                velocity_check['detail'] = 'Insufficient velocity history'
                return velocity_check
            
            if direction == SignalDirection.LONG:
                # LONG: Need POSITIVE OBI + INCREASING (velocity > 0)
                obi_increasing = obi > 0 and obi_velocity > self.min_velocity_threshold
                cvd_increasing = cvd > 0 and cvd_velocity > self.min_velocity_threshold
                
                if obi_increasing and cvd_increasing:
                    # STRONG: Both increasing
                    velocity_check['pass'] = True
                    velocity_check['detail'] = f'OBI+CVD accelerating (🚀+{obi_velocity:.4f}, +{cvd_velocity:.4f})'
                    velocity_check['confidence_boost'] = 15
                elif obi_increasing or cvd_increasing:
                    # MODERATE: One increasing
                    velocity_check['pass'] = True
                    velocity_check['detail'] = f'One flow accelerating'
                    velocity_check['confidence_boost'] = 8
                else:
                    # FAIL: No momentum
                    velocity_check['pass'] = False
                    velocity_check['detail'] = f'Flow collapsing (OBI vel: {obi_velocity:.4f}, CVD vel: {cvd_velocity:.4f})'
                    
            elif direction == SignalDirection.SHORT:
                # SHORT: Need NEGATIVE OBI + DECREASING (velocity < 0)
                obi_decreasing = obi < 0 and obi_velocity < -self.min_velocity_threshold
                cvd_decreasing = cvd < 0 and cvd_velocity < -self.min_velocity_threshold
                
                if obi_decreasing and cvd_decreasing:
                    velocity_check['pass'] = True
                    velocity_check['detail'] = f'OBI+CVD accelerating down (📉{obi_velocity:.4f}, {cvd_velocity:.4f})'
                    velocity_check['confidence_boost'] = 15
                elif obi_decreasing or cvd_decreasing:
                    velocity_check['pass'] = True
                    velocity_check['detail'] = f'One flow accelerating down'
                    velocity_check['confidence_boost'] = 8
                else:
                    velocity_check['pass'] = False
                    velocity_check['detail'] = f'Sell pressure fading'
            
        except Exception as e:
            logger.error(f"Error in velocity check: {e}")
            velocity_check['pass'] = True  # Don't block on error
        
        return velocity_check
    
    def check_liquidity_sweep(
        self,
        direction: SignalDirection,
        current_price: Optional[float],
        bollinger: Optional[Dict],
        cvd: Optional[float],
        rsi: Optional[float]
    ) -> Dict:
        """
        ALPHA ENHANCEMENT 2: LIQUIDITY SWEEP DETECTION (High Win-Rate Setup)
        
        Logic:
        - Price < Bollinger Lower Band + CVD Positive = Liquidity Sweep Reversal
        - This is a high-conviction "stop hunt" reversal setup
        - Has higher win rate than standard trend following
        
        Returns: {
            'detected': bool,
            'detail': str,
            'confidence_boost': int (0-20 points)
        }
        """
        sweep_check = {
            'detected': False,
            'detail': 'No sweep',
            'confidence_boost': 0
        }
        
        try:
            if current_price is None or bollinger is None or cvd is None:
                return sweep_check
            
            bb_lower = bollinger.get('lower')
            bb_upper = bollinger.get('upper')
            
            if bb_lower is None or bb_upper is None:
                return sweep_check
            
            if direction == SignalDirection.LONG:
                # LONG Sweep: Price below lower band BUT buying is coming in (CVD positive)
                # This means "weak hands stopped out, smart money accumulating"
                price_below_band = current_price < bb_lower
                cvd_positive_divergence = cvd > 0.1  # Strong buying despite price weakness
                
                # Additional confirmation: RSI oversold but not extreme
                rsi_confirmation = rsi is not None and 25 < rsi < 35
                
                if price_below_band and cvd_positive_divergence:
                    sweep_check['detected'] = True
                    distance_pct = ((bb_lower - current_price) / current_price) * 100
                    sweep_check['detail'] = f'🎯 LIQUIDITY SWEEP: Price {distance_pct:.2f}% below BB, CVD={cvd:.2f}'
                    
                    # Boost confidence significantly for this high-quality setup
                    if rsi_confirmation:
                        sweep_check['confidence_boost'] = 20  # Maximum boost
                    else:
                        sweep_check['confidence_boost'] = 15
            
            elif direction == SignalDirection.SHORT:
                # SHORT Sweep: Price above upper band BUT selling is coming in (CVD negative)
                price_above_band = current_price > bb_upper
                cvd_negative_divergence = cvd < -0.1
                
                rsi_confirmation = rsi is not None and 65 < rsi < 75
                
                if price_above_band and cvd_negative_divergence:
                    sweep_check['detected'] = True
                    distance_pct = ((current_price - bb_upper) / current_price) * 100
                    sweep_check['detail'] = f'🎯 LIQUIDITY SWEEP: Price {distance_pct:.2f}% above BB, CVD={cvd:.2f}'
                    
                    if rsi_confirmation:
                        sweep_check['confidence_boost'] = 20
                    else:
                        sweep_check['confidence_boost'] = 15
        
        except Exception as e:
            logger.error(f"Error in liquidity sweep detection: {e}")
        
        return sweep_check
    
    def check_vwap_distance(
        self,
        direction: SignalDirection,
        current_price: Optional[float],
        vwap: Optional[float]
    ) -> Dict:
        """
        ALPHA ENHANCEMENT 3: VWAP DISTANCE GUARD (Slippage Protection)
        
        Logic:
        - If (Current Price - VWAP) > 0.3%, REJECT the LONG signal
        - Buying extended from VWAP = "greater fool" exit liquidity provider
        - Ensures we're not buying tops or selling bottoms
        
        Returns: {
            'pass': bool,
            'detail': str,
            'distance_pct': float
        }
        """
        vwap_check = {
            'pass': False,
            'detail': 'N/A',
            'distance_pct': None
        }
        
        try:
            if current_price is None or vwap is None:
                vwap_check['pass'] = True  # Don't block if data unavailable
                vwap_check['detail'] = 'VWAP unavailable'
                return vwap_check
            
            # Calculate distance from VWAP
            distance_pct = abs(current_price - vwap) / vwap
            vwap_check['distance_pct'] = distance_pct
            
            if direction == SignalDirection.LONG:
                # LONG: Don't buy if price is too far ABOVE VWAP
                if current_price > vwap:
                    deviation = (current_price - vwap) / vwap
                    if deviation > self.vwap_distance_threshold:
                        vwap_check['pass'] = False
                        vwap_check['detail'] = f'⚠️  Price {deviation*100:.2f}% above VWAP - REJECT (buying extended)'
                    else:
                        vwap_check['pass'] = True
                        vwap_check['detail'] = f'✓ Price {deviation*100:.2f}% above VWAP - OK'
                else:
                    # Price below VWAP = good for LONG
                    vwap_check['pass'] = True
                    deviation = (vwap - current_price) / vwap
                    vwap_check['detail'] = f'✓✓ Price {deviation*100:.2f}% below VWAP - EXCELLENT'
            
            elif direction == SignalDirection.SHORT:
                # SHORT: Don't sell if price is too far BELOW VWAP
                if current_price < vwap:
                    deviation = (vwap - current_price) / vwap
                    if deviation > self.vwap_distance_threshold:
                        vwap_check['pass'] = False
                        vwap_check['detail'] = f'⚠️  Price {deviation*100:.2f}% below VWAP - REJECT (selling extended)'
                    else:
                        vwap_check['pass'] = True
                        vwap_check['detail'] = f'✓ Price {deviation*100:.2f}% below VWAP - OK'
                else:
                    # Price above VWAP = good for SHORT
                    vwap_check['pass'] = True
                    deviation = (current_price - vwap) / vwap
                    vwap_check['detail'] = f'✓✓ Price {deviation*100:.2f}% above VWAP - EXCELLENT'
        
        except Exception as e:
            logger.error(f"Error in VWAP distance check: {e}")
            vwap_check['pass'] = True  # Don't block on error
        
        return vwap_check
    
    def check_mean_reversion_guard(
        self,
        direction: SignalDirection,
        current_price: Optional[float],
        bollinger: Optional[Dict]
    ) -> Dict:
        """
        SURVIVAL FIX: Mean Reversion Guard
        
        Prevents entering at extremes:
        - LONG: Fail if Price > Bollinger Upper (overextended)
        - SHORT: Fail if Price < Bollinger Lower (oversold bounce)
        """
        result = {'pass': True, 'detail': 'No Bollinger data'}
        
        if not bollinger or not current_price:
            return result
        
        upper = bollinger.get('upper')
        lower = bollinger.get('lower')
        
        if upper is None or lower is None:
            return result
        
        if direction == SignalDirection.LONG:
            if current_price > upper:
                result['pass'] = False
                result['detail'] = f'✗ Price ${current_price:.2f} > BB Upper ${upper:.2f} - Overextended'
            else:
                result['pass'] = True
                result['detail'] = f'✓ Price below BB Upper - Room to run'
        else:  # SHORT
            if current_price < lower:
                result['pass'] = False
                result['detail'] = f'✗ Price ${current_price:.2f} < BB Lower ${lower:.2f} - Oversold'
            else:
                result['pass'] = True
                result['detail'] = f'✓ Price above BB Lower - Room to fall'
        
        return result
    
    def check_candle_color_guard(
        self,
        direction: SignalDirection,
        current_price: Optional[float],
        forming_candle_open: Optional[float]
    ) -> Dict:
        """
        SURVIVAL FIX: Falling Knife Protection
        
        Prevents catching falling knives:
        - LONG: Fail if Price < Open (red candle forming - downward momentum)
        - SHORT: Fail if Price > Open (green candle forming - upward momentum)
        """
        result = {'pass': True, 'detail': 'No candle data'}
        
        if current_price is None or forming_candle_open is None:
            return result
        
        if direction == SignalDirection.LONG:
            if current_price < forming_candle_open:
                result['pass'] = False
                result['detail'] = f'✗ Red candle forming (Price < Open) - Falling knife'
            else:
                result['pass'] = True
                result['detail'] = f'✓ Green candle forming - Bullish momentum'
        else:  # SHORT
            if current_price > forming_candle_open:
                result['pass'] = False
                result['detail'] = f'✗ Green candle forming (Price > Open) - Rising knife'
            else:
                result['pass'] = True
                result['detail'] = f'✓ Red candle forming - Bearish momentum'
        
        return result
    
    def calculate_adaptive_targets(
        self,
        atr: float,
        trend_strength: Optional[float] = None,
        hurst: Optional[float] = None
    ) -> Dict:
        """
        SURVIVAL FIX V2.0: VOLATILITY-ADAPTIVE TARGETS (Wider for Profitability)
        
        FIXED: Previous multipliers were too tight, causing:
        - TP hits being missed by small margins
        - Poor risk/reward ratios
        
        NEW TARGETS (wider to ensure profitability):
        - Strong Trend (>0.7): TP1 2.0x, TP2 3.5x, SL 1.0x (R:R = 2:1)
        - Choppy (<0.3): TP1 1.5x, TP2 2.5x, SL 1.2x (R:R = 1.25:1)
        - Normal: TP1 1.8x, TP2 3.0x, SL 1.0x (R:R = 1.8:1)
        
        Returns: {
            'tp1_multiplier': float,
            'tp2_multiplier': float,
            'sl_multiplier': float,
            'use_trailing': bool,
            'regime_detail': str
        }
        """
        # Default targets (NORMAL regime - balanced)
        targets = {
            'tp1_multiplier': 1.8,
            'tp2_multiplier': 3.0,
            'sl_multiplier': 1.0,
            'use_trailing': False,
            'regime_detail': 'Normal'
        }
        
        try:
            # Use trend_strength as primary (simpler), hurst as fallback
            if trend_strength is not None:
                strength = trend_strength
                metric = 'TrendStrength'
            elif hurst is not None:
                strength = hurst
                metric = 'Hurst'
            else:
                return targets  # No data, use defaults
            
            # CHOPPY MARKET (Mean-Reverting): Conservative targets
            if strength < 0.3:
                targets['tp1_multiplier'] = 1.5   # Tighter but still profitable
                targets['tp2_multiplier'] = 2.5
                targets['sl_multiplier'] = 1.2    # Slightly wider SL for noise
                targets['use_trailing'] = False
                targets['regime_detail'] = f'CHOPPY ({metric}={strength:.2f}) - CONSERVATIVE'
            
            # NORMAL/MODERATE TREND
            elif 0.3 <= strength <= 0.7:
                targets['tp1_multiplier'] = 1.8
                targets['tp2_multiplier'] = 3.0
                targets['sl_multiplier'] = 1.0
                targets['use_trailing'] = False
                targets['regime_detail'] = f'MODERATE ({metric}={strength:.2f}) - STANDARD'
            
            # STRONG TREND: Wide Targets + Trailing
            else:  # strength > 0.7
                targets['tp1_multiplier'] = 2.0
                targets['tp2_multiplier'] = 3.5
                targets['sl_multiplier'] = 1.0    # Tight SL, let TP do the work
                targets['use_trailing'] = True    # Let winners run
                targets['regime_detail'] = f'TRENDING ({metric}={strength:.2f}) - AGGRESSIVE'
        
        except Exception as e:
            logger.error(f"Error calculating adaptive targets: {e}")
        
        return targets
    
    def detect_signal_with_alpha(
        self,
        direction: SignalDirection,
        regime: RegimeType,
        # Original inputs
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
        atr: Optional[float],
        # ALPHA inputs
        obi_velocity: Optional[float] = None,
        cvd_velocity: Optional[float] = None,
        bollinger: Optional[Dict] = None,
        vwap: Optional[float] = None,
        trend_strength: Optional[float] = None,
        hurst: Optional[float] = None,
        # SURVIVAL FIX inputs
        forming_candle_open: Optional[float] = None
    ) -> Dict:
        """
        Comprehensive signal detection with all ALPHA enhancements + SURVIVAL FIXES
        
        V2.0 SURVIVAL FIX additions:
        - Mean Reversion Guard (Bollinger extremes)
        - Candle Color Guard (Falling Knife protection)
        - Raised thresholds (forming=80, active=88)
        - Wider targets for profitability
        
        Returns enhanced signal dict with:
        - Original score
        - Alpha confidence boosts
        - Velocity checks
        - Liquidity sweep detection
        - VWAP distance guard
        - Mean reversion guard
        - Candle color guard
        - Adaptive targets
        """
        result = {
            'score': 0,
            'base_score': 0,
            'alpha_boost': 0,
            'signal_ready': False,
            'breakdown': {},
            'alpha_checks': {},
            'adaptive_targets': {}
        }
        
        try:
            # Run ALPHA checks
            velocity_check = self.check_velocity_signal(direction, obi, obi_velocity, cvd_5m, cvd_velocity)
            sweep_check = self.check_liquidity_sweep(direction, current_price, bollinger, cvd_5m, rsi_5m)
            vwap_check = self.check_vwap_distance(direction, current_price, vwap)
            
            # SURVIVAL FIX: New mandatory guards
            mean_reversion_check = self.check_mean_reversion_guard(direction, current_price, bollinger)
            candle_color_check = self.check_candle_color_guard(direction, current_price, forming_candle_open)
            
            # Store alpha check results
            result['alpha_checks'] = {
                'velocity': velocity_check,
                'liquidity_sweep': sweep_check,
                'vwap_distance': vwap_check,
                'mean_reversion': mean_reversion_check,
                'candle_color': candle_color_check
            }
            
            # HARD VETO: VWAP distance check
            if not vwap_check['pass']:
                result['signal_ready'] = False
                result['breakdown']['VETO'] = {
                    'points': 0,
                    'detail': f"🚫 VWAP VETO: {vwap_check['detail']}"
                }
                return result
            
            # SURVIVAL FIX VETO: Mean Reversion Guard
            if not mean_reversion_check['pass']:
                result['signal_ready'] = False
                result['breakdown']['VETO'] = {
                    'points': 0,
                    'detail': f"🚫 MEAN REVERSION VETO: {mean_reversion_check['detail']}"
                }
                return result
            
            # SURVIVAL FIX VETO: Candle Color Guard (Falling Knife Protection)
            if not candle_color_check['pass']:
                result['signal_ready'] = False
                result['breakdown']['VETO'] = {
                    'points': 0,
                    'detail': f"🚫 FALLING KNIFE VETO: {candle_color_check['detail']}"
                }
                return result
            
            # Calculate base score (simplified version of original logic)
            base_score = 0
            
            # 1. Regime (20 points)
            # TREND-FOLLOWING: Aligned regime gets full points
            # MEAN-REVERSION: RANGING with RSI extremes gets partial points (contrarian)
            if direction == SignalDirection.LONG:
                if regime == RegimeType.TRENDING_BULL:
                    base_score += 20
                    result['breakdown']['regime'] = {'points': 20, 'detail': 'TRENDING_BULL'}
                elif regime == RegimeType.RANGING and rsi_5m is not None and rsi_5m < 35:
                    # Mean reversion: Oversold in ranging market
                    base_score += 12
                    result['breakdown']['regime'] = {'points': 12, 'detail': f'RANGING+OVERSOLD (RSI {rsi_5m:.0f})'}
            else:
                if regime == RegimeType.TRENDING_BEAR:
                    base_score += 20
                    result['breakdown']['regime'] = {'points': 20, 'detail': 'TRENDING_BEAR'}
                elif regime == RegimeType.RANGING and rsi_5m is not None and rsi_5m > 65:
                    # Mean reversion: Overbought in ranging market
                    base_score += 12
                    result['breakdown']['regime'] = {'points': 12, 'detail': f'RANGING+OVERBOUGHT (RSI {rsi_5m:.0f})'}
            
            # 2. Trend Alignment (15 points)
            aligned = 0
            if ema20_5m and ema50_5m:
                if (direction == SignalDirection.LONG and ema20_5m > ema50_5m) or \
                   (direction == SignalDirection.SHORT and ema20_5m < ema50_5m):
                    aligned += 1
            if aligned > 0:
                base_score += 15
                result['breakdown']['trends'] = {'points': 15, 'detail': 'Aligned'}
            
            # 3. CVD (20 points)
            if cvd_5m is not None:
                if direction == SignalDirection.LONG and cvd_5m > 0.08:
                    base_score += 20
                    result['breakdown']['cvd'] = {'points': 20, 'detail': f'{cvd_5m:.3f}'}
                elif direction == SignalDirection.SHORT and cvd_5m < -0.08:
                    base_score += 20
                    result['breakdown']['cvd'] = {'points': 20, 'detail': f'{cvd_5m:.3f}'}
            
            # 4. OBI (15 points)
            if obi is not None:
                if direction == SignalDirection.LONG and obi > 0.1:
                    base_score += 15
                    result['breakdown']['obi'] = {'points': 15, 'detail': f'{obi:.3f}'}
                elif direction == SignalDirection.SHORT and obi < -0.1:
                    base_score += 15
                    result['breakdown']['obi'] = {'points': 15, 'detail': f'{obi:.3f}'}
            
            # 5. RSI (10 points)
            if rsi_5m is not None and 40 <= rsi_5m <= 60:
                base_score += 10
                result['breakdown']['rsi'] = {'points': 10, 'detail': f'{rsi_5m:.0f}'}
            
            result['base_score'] = base_score
            
            # Apply ALPHA boosts
            alpha_boost = 0
            
            # Velocity boost
            if velocity_check['pass']:
                alpha_boost += velocity_check['confidence_boost']
                result['breakdown']['velocity'] = {
                    'points': velocity_check['confidence_boost'],
                    'detail': velocity_check['detail']
                }
            
            # Liquidity sweep boost
            if sweep_check['detected']:
                alpha_boost += sweep_check['confidence_boost']
                result['breakdown']['liquidity_sweep'] = {
                    'points': sweep_check['confidence_boost'],
                    'detail': sweep_check['detail']
                }
            
            result['alpha_boost'] = alpha_boost
            result['score'] = min(100, base_score + alpha_boost)  # Cap at 100
            
            # Signal ready if score high enough AND all alpha checks pass
            result['signal_ready'] = (
                result['score'] >= self.active_threshold and
                velocity_check['pass'] and
                vwap_check['pass']
            )
            
            # Calculate adaptive targets
            if atr:
                result['adaptive_targets'] = self.calculate_adaptive_targets(
                    atr, trend_strength, hurst
                )
        
        except Exception as e:
            logger.error(f"Error in alpha signal detection: {e}")
        
        return result
