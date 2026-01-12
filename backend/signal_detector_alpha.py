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
        # V2.1 REBALANCED: Quality + Usable Frequency
        self.forming_threshold = 70   # Lowered for better signal detection
        self.active_threshold = 75    # Rebalanced from 88 (was mathematically impossible)
        
        # Hard gate limits
        self.max_ema_distance_pct = 1.0  # Must be within 1% of EMA20
        self.max_spread_bps = 5.0        # Spread must be < 5 bps
        self.min_cvd_threshold = 0.05    # Lowered from 0.08 for realistic signals
        self.min_obi_threshold = 0.08    # Lowered from 0.1 for realistic signals
        self.min_atr = 100               # Minimum ATR for sufficient volatility ($100)
        
        # ALPHA ENHANCEMENTS
        self.vwap_distance_threshold = 0.02  # 2% max distance from VWAP (adjusted for crypto volatility)
        self.min_velocity_threshold = 0.001   # Minimum positive velocity for LONG (acceleration check)
    
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
        bollinger: Optional[Dict],
        regime: Optional[RegimeType] = None
    ) -> Dict:
        """
        V2.1 REBALANCED: Mean Reversion Guard (Advisory Only)
        
        Now REGIME-AWARE:
        - TRENDING: Allow band pushes (let winners run) - NO PENALTY
        - RANGING: Warn on extremes but don't veto - ADVISORY
        
        Returns score penalty (not a hard veto)
        """
        result = {
            'pass': True, 
            'detail': 'No Bollinger data',
            'score_penalty': 0  # NEW: Advisory penalty instead of veto
        }
        
        if not bollinger or not current_price:
            return result
        
        upper = bollinger.get('upper')
        lower = bollinger.get('lower')
        
        if upper is None or lower is None:
            return result
        
        # In TRENDING regimes, allow band pushes (momentum continuation)
        if regime in [RegimeType.TRENDING_BULL, RegimeType.TRENDING_BEAR]:
            result['pass'] = True
            result['detail'] = f'✓ TRENDING regime - Band push allowed'
            result['score_penalty'] = 0
            return result
        
        # In RANGING markets, apply advisory penalty (not veto)
        if direction == SignalDirection.LONG:
            if current_price > upper:
                result['pass'] = True  # Changed from False - advisory only
                result['detail'] = f'⚠️ Price ${current_price:.2f} > BB Upper ${upper:.2f} (RANGING - risk of pullback)'
                result['score_penalty'] = -10  # Reduce score but don't block
            else:
                result['pass'] = True
                result['detail'] = f'✓ Price below BB Upper - Room to run'
                result['score_penalty'] = 0
        else:  # SHORT
            if current_price < lower:
                result['pass'] = True  # Changed from False - advisory only
                result['detail'] = f'⚠️ Price ${current_price:.2f} < BB Lower ${lower:.2f} (RANGING - risk of bounce)'
                result['score_penalty'] = -10  # Reduce score but don't block
            else:
                result['pass'] = True
                result['detail'] = f'✓ Price above BB Lower - Room to fall'
                result['score_penalty'] = 0
        
        return result
    
    def check_candle_color_guard(
        self,
        direction: SignalDirection,
        current_price: Optional[float],
        forming_candle_open: Optional[float]
    ) -> Dict:
        """
        V2.1 REMOVED: Candle Color Guard
        
        REASON: For scalping, we WANT to buy red candles (dip) if CVD is strong.
        Waiting for green confirmation is too slow and misses entries.
        
        This function now returns advisory info only (no blocking).
        """
        result = {'pass': True, 'detail': 'Advisory only (not enforced)'}
        
        if current_price is None or forming_candle_open is None:
            return result
        
        # Advisory only - provide info but don't block
        if direction == SignalDirection.LONG:
            if current_price < forming_candle_open:
                result['pass'] = True  # Changed from False
                result['detail'] = f'ℹ️ Red candle (buying dip if flow strong)'
            else:
                result['pass'] = True
                result['detail'] = f'ℹ️ Green candle (momentum entry)'
        else:  # SHORT
            if current_price > forming_candle_open:
                result['pass'] = True  # Changed from False
                result['detail'] = f'ℹ️ Green candle (selling rip if flow weak)'
            else:
                result['pass'] = True
                result['detail'] = f'ℹ️ Red candle (momentum entry)'
        
        return result
    
    def calculate_adaptive_targets(
        self,
        atr: float,
        trend_strength: Optional[float] = None,
        hurst: Optional[float] = None
    ) -> Dict:
        """
        V2.2 WIN RATE FIX: WIDER STOP LOSSES (Reduce premature stop-outs)
        
        USER FEEDBACK: Win rate < 50% due to tight SLs
        
        SOLUTION: Widen SL multipliers to give trades breathing room
        - Strong Trend (>0.7): TP1 2.0x, TP2 4.0x, SL 1.5x (R:R = 1.33:1)
        - Choppy (<0.3): TP1 1.8x, TP2 3.0x, SL 2.0x (R:R = 0.9:1 but higher win rate)
        - Normal: TP1 2.0x, TP2 3.5x, SL 1.8x (R:R = 1.1:1)
        
        PHILOSOPHY: Better to have 65% win rate with 1:1 R:R than 40% with 2:1 R:R
        
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
            'tp1_multiplier': 2.0,  # Widened from 1.8
            'tp2_multiplier': 3.5,  # Widened from 3.0
            'sl_multiplier': 1.8,   # WIDENED from 1.0 (+80%)
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
            
            # CHOPPY MARKET (Mean-Reverting): WIDEST SL (most noise)
            if strength < 0.3:
                targets['tp1_multiplier'] = 1.8   # Slightly wider from 1.5
                targets['tp2_multiplier'] = 3.0   # Wider from 2.5
                targets['sl_multiplier'] = 2.0    # WIDENED from 1.2 (+67%)
                targets['use_trailing'] = False
                targets['regime_detail'] = f'CHOPPY ({metric}={strength:.2f}) - WIDE_SL'
            
            # NORMAL/MODERATE TREND
            elif 0.3 <= strength <= 0.7:
                targets['tp1_multiplier'] = 2.0   # Widened from 1.8
                targets['tp2_multiplier'] = 3.5   # Widened from 3.0
                targets['sl_multiplier'] = 1.8    # WIDENED from 1.0 (+80%)
                targets['use_trailing'] = False
                targets['regime_detail'] = f'MODERATE ({metric}={strength:.2f}) - WIDE_SL'
            
            # STRONG TREND: Wide Targets + Moderate SL
            else:  # strength > 0.7
                targets['tp1_multiplier'] = 2.5   # Widened from 2.0
                targets['tp2_multiplier'] = 4.0   # Widened from 3.5
                targets['sl_multiplier'] = 1.5    # WIDENED from 1.0 (+50%)
                targets['use_trailing'] = True    # Let winners run
                targets['regime_detail'] = f'TRENDING ({metric}={strength:.2f}) - MOMENTUM'
        
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
        Comprehensive signal detection with all ALPHA enhancements + V2.1 REBALANCED
        
        V2.1 REBALANCED changes:
        - Active threshold: 88 → 75 (realistic)
        - Candle Color Guard: REMOVED (buy dips with strong flow)
        - Mean Reversion Guard: ADVISORY only, regime-aware
        - CVD/OBI thresholds: Lowered (0.05/0.08)
        - Regime scoring: More generous in RANGING
        
        Returns enhanced signal dict with:
        - Original score
        - Alpha confidence boosts
        - Velocity checks (weighted heavily)
        - Liquidity sweep detection
        - VWAP distance guard
        - Advisory checks (non-blocking)
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
            
            # V2.1: Advisory checks (regime-aware, non-blocking)
            mean_reversion_check = self.check_mean_reversion_guard(direction, current_price, bollinger, regime)
            candle_color_check = self.check_candle_color_guard(direction, current_price, forming_candle_open)
            
            # Store alpha check results
            result['alpha_checks'] = {
                'velocity': velocity_check,
                'liquidity_sweep': sweep_check,
                'vwap_distance': vwap_check,
                'mean_reversion': mean_reversion_check,
                'candle_color': candle_color_check
            }
            
            # HARD VETO: VWAP distance check (only remaining hard veto)
            if not vwap_check['pass']:
                result['signal_ready'] = False
                result['breakdown']['VETO'] = {
                    'points': 0,
                    'detail': f"🚫 VWAP VETO: {vwap_check['detail']}"
                }
                return result
            
            # V2.1: Mean Reversion is now advisory - apply score penalty instead of veto
            score_penalty = mean_reversion_check.get('score_penalty', 0)
            
            # Calculate base score (simplified version of original logic)
            base_score = 0
            
            # 1. Regime (20 points) - V2.1: More generous in RANGING + HFT Mean Reversion
            if direction == SignalDirection.LONG:
                if regime == RegimeType.TRENDING_BULL:
                    base_score += 20
                    result['breakdown']['regime'] = {'points': 20, 'detail': 'TRENDING_BULL'}
                elif regime == RegimeType.RANGING:
                    # HFT MEAN REVERSION: Enhanced Bollinger + RSI logic for scalping
                    # HIGH QUALITY: Price < BB Lower AND RSI < 30 (extreme oversold)
                    if (bollinger and current_price and 
                        current_price < bollinger.get('lower', float('inf')) and
                        rsi_5m is not None and rsi_5m < 30):
                        base_score += 20  # Full points for perfect mean reversion setup
                        result['breakdown']['regime'] = {
                            'points': 20, 
                            'detail': f'RANGING+MEAN_REVERSION (Price<BB_Lower, RSI={rsi_5m:.0f}) - HIGH QUALITY'
                        }
                    # GOOD: RSI oversold (< 35) even without Bollinger confirmation
                    elif rsi_5m is not None and rsi_5m < 35:
                        base_score += 15  # Good mean reversion signal
                        result['breakdown']['regime'] = {'points': 15, 'detail': f'RANGING+OVERSOLD (RSI {rsi_5m:.0f})'}
                    # NEUTRAL: Just ranging
                    else:
                        base_score += 8  # Partial credit for ranging
                        result['breakdown']['regime'] = {'points': 8, 'detail': 'RANGING (neutral)'}
            else:
                if regime == RegimeType.TRENDING_BEAR:
                    base_score += 20
                    result['breakdown']['regime'] = {'points': 20, 'detail': 'TRENDING_BEAR'}
                elif regime == RegimeType.RANGING:
                    # HFT MEAN REVERSION: Enhanced Bollinger + RSI logic for scalping
                    # HIGH QUALITY: Price > BB Upper AND RSI > 70 (extreme overbought)
                    if (bollinger and current_price and 
                        current_price > bollinger.get('upper', float('-inf')) and
                        rsi_5m is not None and rsi_5m > 70):
                        base_score += 20  # Full points for perfect mean reversion setup
                        result['breakdown']['regime'] = {
                            'points': 20,
                            'detail': f'RANGING+MEAN_REVERSION (Price>BB_Upper, RSI={rsi_5m:.0f}) - HIGH QUALITY'
                        }
                    # GOOD: RSI overbought (> 65) even without Bollinger confirmation
                    elif rsi_5m is not None and rsi_5m > 65:
                        base_score += 15  # Good mean reversion signal
                        result['breakdown']['regime'] = {'points': 15, 'detail': f'RANGING+OVERBOUGHT (RSI {rsi_5m:.0f})'}
                    # NEUTRAL: Just ranging
                    else:
                        base_score += 8  # Partial credit for ranging
                        result['breakdown']['regime'] = {'points': 8, 'detail': 'RANGING (neutral)'}
                        

            
            # 2. Trend Alignment (15 points)
            aligned = 0
            if ema20_5m and ema50_5m:
                if (direction == SignalDirection.LONG and ema20_5m > ema50_5m) or \
                   (direction == SignalDirection.SHORT and ema20_5m < ema50_5m):
                    aligned += 1
            if aligned > 0:
                base_score += 15
                result['breakdown']['trends'] = {'points': 15, 'detail': 'Aligned'}
            
            # 3. CVD (20 points) - V2.1: Lowered threshold to 0.05
            if cvd_5m is not None:
                if direction == SignalDirection.LONG and cvd_5m > self.min_cvd_threshold:
                    base_score += 20
                    result['breakdown']['cvd'] = {'points': 20, 'detail': f'{cvd_5m:.3f}'}
                elif direction == SignalDirection.SHORT and cvd_5m < -self.min_cvd_threshold:
                    base_score += 20
                    result['breakdown']['cvd'] = {'points': 20, 'detail': f'{cvd_5m:.3f}'}
            
            # 4. OBI (15 points) - V2.1: Lowered threshold to 0.08
            if obi is not None:
                if direction == SignalDirection.LONG and obi > self.min_obi_threshold:
                    base_score += 15
                    result['breakdown']['obi'] = {'points': 15, 'detail': f'{obi:.3f}'}
                elif direction == SignalDirection.SHORT and obi < -self.min_obi_threshold:
                    base_score += 15
                    result['breakdown']['obi'] = {'points': 15, 'detail': f'{obi:.3f}'}
            
            # 5. RSI (10 points)
            if rsi_5m is not None and 40 <= rsi_5m <= 60:
                base_score += 10
                result['breakdown']['rsi'] = {'points': 10, 'detail': f'{rsi_5m:.0f}'}
            
            result['base_score'] = base_score
            
            # Apply ALPHA boosts
            alpha_boost = 0
            
            # TOP 0.1% SCALPER: Order Flow Imbalance boost (HIGHEST PRIORITY)
            # This is extracted from kwargs in detect_signal_with_alpha
            ofi = kwargs.get('ofi')
            if ofi is not None:
                ofi_threshold = 0.6  # Institutional-grade threshold
                if direction == SignalDirection.LONG and ofi > ofi_threshold:
                    ofi_boost = min(20, int((ofi - ofi_threshold) * 50))  # Up to 20 pts
                    alpha_boost += ofi_boost
                    result['breakdown']['order_flow'] = {
                        'points': ofi_boost,
                        'detail': f'OFI {ofi:.3f} - Strong buying pressure'
                    }
                elif direction == SignalDirection.SHORT and ofi < -ofi_threshold:
                    ofi_boost = min(20, int((abs(ofi) - ofi_threshold) * 50))  # Up to 20 pts
                    alpha_boost += ofi_boost
                    result['breakdown']['order_flow'] = {
                        'points': ofi_boost,
                        'detail': f'OFI {ofi:.3f} - Strong selling pressure'
                    }
            
            # Velocity boost (WEIGHTED HEAVILY per user request)
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
            
            # Apply advisory penalty from mean reversion
            total_score = base_score + alpha_boost + score_penalty
            result['score'] = max(0, min(100, total_score))  # Clamp to [0, 100]
            
            if score_penalty < 0:
                result['breakdown']['mean_reversion_advisory'] = {
                    'points': score_penalty,
                    'detail': mean_reversion_check['detail']
                }
            
            # Signal ready if score high enough AND velocity check passes
            # V2.1: Removed candle color and mean reversion hard checks
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
