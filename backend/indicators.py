import logging
from typing import List, Optional
from candle_builder import Candle

logger = logging.getLogger(__name__)

class Indicators:
    def __init__(self):
        # Smoothing factor for exponential smoothing
        self.alpha = 0.1
        
        # Smoothed values
        self.obi_smoothed: Optional[float] = None
        self.cvd_1m_smoothed: Optional[float] = None
        self.cvd_5m_smoothed: Optional[float] = None
        self.depth_smoothed: Optional[float] = None
        
        # ALPHA ENHANCEMENT: Velocity tracking for anti-spoofing
        self.obi_history = []  # Track last N OBI values for ROC
        self.cvd_history = []  # Track last N CVD values for ROC
        self.max_history_length = 10  # Keep last 10 ticks
        
    def calculate_ema(self, candles: List[Candle], period: int) -> Optional[float]:
        """Calculate EMA for given period - returns None if insufficient data"""
        try:
            if len(candles) == 0:
                return None
            
            # Get closing prices
            closes = [c.close for c in candles if c.close is not None]
            if len(closes) == 0:
                return None
            
            # STRICT: Require full period of data, no approximation
            if len(closes) < period:
                return None
            
            # Calculate EMA
            multiplier = 2 / (period + 1)
            ema = closes[0]
            
            for price in closes[1:]:
                ema = (price - ema) * multiplier + ema
            
            return ema
        except Exception as e:
            logger.error(f"Error calculating EMA: {e}")
            return None
    
    def calculate_atr(self, candles: List[Candle], period: int = 14) -> Optional[float]:
        """Calculate ATR (Average True Range)"""
        try:
            if len(candles) < period + 1:
                return None
            
            true_ranges = []
            for i in range(1, len(candles)):
                prev_close = candles[i-1].close
                current_high = candles[i].high
                current_low = candles[i].low
                
                if prev_close is None or current_high is None or current_low is None:
                    continue
                
                tr = max(
                    current_high - current_low,
                    abs(current_high - prev_close),
                    abs(current_low - prev_close)
                )
                true_ranges.append(tr)
            
            if len(true_ranges) < period:
                return None
            
            # Calculate ATR as simple moving average of true ranges
            atr = sum(true_ranges[-period:]) / period
            return atr
            
        except Exception as e:
            logger.error(f"Error calculating ATR: {e}")
            return None
    
    def calculate_rsi(self, candles: List[Candle], period: int = 14) -> Optional[float]:
        """Calculate RSI (Relative Strength Index)"""
        try:
            if len(candles) < period + 1:
                return None
            
            closes = [c.close for c in candles[-(period+1):] if c.close is not None]
            if len(closes) < period + 1:
                return None
            
            # Calculate price changes
            gains = []
            losses = []
            
            for i in range(1, len(closes)):
                change = closes[i] - closes[i-1]
                if change > 0:
                    gains.append(change)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(change))
            
            if len(gains) < period:
                return None
            
            # Calculate average gain and loss
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            
            if avg_loss == 0:
                return 100.0
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
            return rsi
            
        except Exception as e:
            logger.error(f"Error calculating RSI: {e}")
            return None
    
    def calculate_obi(self, orderbook: dict) -> Optional[float]:
        """Calculate OBI (Order Book Imbalance) from top 10 levels"""
        try:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            
            if not bids or not asks:
                return None
            
            # Sum top 10 levels
            bid_volume = sum(float(bid[1]) for bid in bids[:10])
            ask_volume = sum(float(ask[1]) for ask in asks[:10])
            
            total_volume = bid_volume + ask_volume
            if total_volume == 0:
                return None
            
            obi = (bid_volume - ask_volume) / total_volume
            
            # Apply exponential smoothing
            if self.obi_smoothed is None:
                self.obi_smoothed = obi
            else:
                self.obi_smoothed = self.alpha * obi + (1 - self.alpha) * self.obi_smoothed
            
            return self.obi_smoothed
            
        except Exception as e:
            logger.error(f"Error calculating OBI: {e}")
            return None
    
    def calculate_spread(self, orderbook: dict) -> Optional[float]:
        """Calculate spread in basis points"""
        try:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            
            if not bids or not asks:
                return None
            
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            
            if best_bid == 0 or best_ask == 0:
                return None
            
            mid_price = (best_bid + best_ask) / 2
            spread_bps = ((best_ask - best_bid) / mid_price) * 10000
            
            return spread_bps
            
        except Exception as e:
            logger.error(f"Error calculating spread: {e}")
            return None
    
    def calculate_depth(self, orderbook: dict) -> Optional[float]:
        """Calculate depth as minimum of bid/ask depth for top 10 levels"""
        try:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            
            if not bids or not asks:
                return None
            
            # Calculate price * size for top 10 levels
            bid_depth = sum(float(bid[0]) * float(bid[1]) for bid in bids[:10])
            ask_depth = sum(float(ask[0]) * float(ask[1]) for ask in asks[:10])
            
            depth = min(bid_depth, ask_depth)
            
            # Apply exponential smoothing
            if self.depth_smoothed is None:
                self.depth_smoothed = depth
            else:
                self.depth_smoothed = self.alpha * depth + (1 - self.alpha) * self.depth_smoothed
            
            return self.depth_smoothed
            
        except Exception as e:
            logger.error(f"Error calculating depth: {e}")
            return None
    
    def calculate_cvd(self, trades: List[dict], window_seconds: int) -> Optional[float]:
        """Calculate CVD (Cumulative Volume Delta) for given time window"""
        try:
            if not trades:
                return None
            
            import time
            current_time = int(time.time() * 1000)
            cutoff_time = current_time - (window_seconds * 1000)
            
            buy_volume = 0
            sell_volume = 0
            
            for trade in trades:
                trade_time = int(trade.get('ts', 0))
                if trade_time < cutoff_time:
                    continue
                
                volume = float(trade.get('sz', 0))
                side = trade.get('side', '')
                
                if side == 'buy':
                    buy_volume += volume
                elif side == 'sell':
                    sell_volume += volume
            
            total_volume = buy_volume + sell_volume
            if total_volume == 0:
                return None
            
            cvd = (buy_volume - sell_volume) / total_volume
            
            # Apply smoothing based on window
            if window_seconds == 60:
                if self.cvd_1m_smoothed is None:
                    self.cvd_1m_smoothed = cvd
                else:
                    self.cvd_1m_smoothed = self.alpha * cvd + (1 - self.alpha) * self.cvd_1m_smoothed
                return self.cvd_1m_smoothed
            elif window_seconds == 300:
                if self.cvd_5m_smoothed is None:
                    self.cvd_5m_smoothed = cvd
                else:
                    self.cvd_5m_smoothed = self.alpha * cvd + (1 - self.alpha) * self.cvd_5m_smoothed
                return self.cvd_5m_smoothed
            

    # ==================== ALPHA ENHANCEMENTS ====================
    
    def calculate_roc(self, history: List[float], periods: int = 3) -> Optional[float]:
        """
        Calculate Rate of Change (ROC) - VELOCITY SIGNAL
        Returns the slope/velocity of the indicator over last N periods
        
        Purpose: Detect if OBI/CVD is INCREASING (momentum) or DECREASING (spoofing/pullback)
        """
        try:
            if len(history) < periods + 1:
                return None
            
            # Get last N+1 values
            recent = history[-(periods+1):]
            
            # Calculate simple linear slope
            # slope = (last_value - first_value) / periods
            slope = (recent[-1] - recent[0]) / periods
            
            return slope
            
        except Exception as e:
            logger.error(f"Error calculating ROC: {e}")
            return None
    
    def get_obi_velocity(self) -> Optional[float]:
        """Get OBI velocity (rate of change over last 3 ticks)"""
        return self.calculate_roc(self.obi_history, periods=3)
    
    def get_cvd_velocity(self) -> Optional[float]:
        """Get CVD velocity (rate of change over last 3 ticks)"""
        return self.calculate_roc(self.cvd_history, periods=3)
    
    def calculate_bollinger_bands(self, candles: List[Candle], period: int = 20, std_dev: float = 2.0) -> Optional[Dict]:
        """
        Calculate Bollinger Bands - for LIQUIDITY SWEEP detection
        
        Returns: {
            'upper': float,
            'middle': float (SMA),
            'lower': float
        }
        """
        try:
            if len(candles) < period:
                return None
            
            # Get closing prices
            closes = [c.close for c in candles[-period:] if c.close is not None]
            if len(closes) < period:
                return None
            
            # Calculate SMA (middle band)
            sma = sum(closes) / len(closes)
            
            # Calculate standard deviation
            variance = sum((x - sma) ** 2 for x in closes) / len(closes)
            std = variance ** 0.5
            
            return {
                'upper': sma + (std_dev * std),
                'middle': sma,
                'lower': sma - (std_dev * std),
                'std': std
            }
            
        except Exception as e:
            logger.error(f"Error calculating Bollinger Bands: {e}")
            return None
    
    def calculate_vwap(self, candles: List[Candle]) -> Optional[float]:
        """
        Calculate Volume Weighted Average Price (VWAP) - for SLIPPAGE PROTECTION
        
        VWAP = Σ(Price * Volume) / Σ(Volume)
        
        Purpose: Detect if price is extended from fair value
        """
        try:
            if len(candles) == 0:
                return None
            
            # Get today's candles (or use all available if < 1 day)
            recent_candles = candles[-100:]  # Last 100 candles for rolling VWAP
            
            total_pv = 0  # Price * Volume
            total_volume = 0
            
            for candle in recent_candles:
                if candle.close is not None and candle.volume is not None:
                    # Use typical price (H+L+C)/3 for VWAP
                    if candle.high and candle.low:
                        typical_price = (candle.high + candle.low + candle.close) / 3
                    else:
                        typical_price = candle.close
                    
                    total_pv += typical_price * candle.volume
                    total_volume += candle.volume
            
            if total_volume == 0:
                return None
            
            vwap = total_pv / total_volume
            return vwap
            
        except Exception as e:
            logger.error(f"Error calculating VWAP: {e}")
            return None
    
    def calculate_hurst_exponent(self, candles: List[Candle], period: int = 50) -> Optional[float]:
        """
        Calculate Hurst Exponent - for TREND STRENGTH measurement
        
        Hurst < 0.5: Mean-reverting (choppy) - use tight targets
        Hurst = 0.5: Random walk
        Hurst > 0.5: Trending (persistent) - use wide targets or trailing stops
        
        Simplified RS analysis (Rescaled Range)
        """
        try:
            if len(candles) < period:
                return None
            
            closes = [c.close for c in candles[-period:] if c.close is not None]
            if len(closes) < period:
                return None
            
            # Calculate log returns
            log_returns = []
            for i in range(1, len(closes)):
                if closes[i-1] > 0 and closes[i] > 0:
                    log_returns.append(log(closes[i] / closes[i-1]))
            
            if len(log_returns) < 10:
                return None
            
            # Calculate mean return
            mean_return = sum(log_returns) / len(log_returns)
            
            # Calculate cumulative deviations from mean
            cumulative_dev = []
            cumsum = 0
            for ret in log_returns:
                cumsum += (ret - mean_return)
                cumulative_dev.append(cumsum)
            
            # Calculate range
            R = max(cumulative_dev) - min(cumulative_dev)
            
            # Calculate standard deviation
            variance = sum((x - mean_return) ** 2 for x in log_returns) / len(log_returns)
            S = variance ** 0.5
            
            if S == 0:
                return 0.5  # Random walk default
            
            # RS ratio
            RS = R / S
            
            # Hurst exponent approximation: H ≈ log(RS) / log(N)
            import math
            N = len(log_returns)
            H = math.log(RS) / math.log(N) if RS > 0 else 0.5
            
            # Clamp to valid range [0, 1]
            H = max(0.0, min(1.0, H))
            
            return H
            
        except Exception as e:
            logger.error(f"Error calculating Hurst exponent: {e}")
            return 0.5  # Default to random walk
    
    def calculate_trend_strength(self, candles: List[Candle], period: int = 20) -> Optional[float]:
        """
        Simplified Trend Strength Index (alternative to Hurst)
        
        Returns value 0.0 to 1.0:
        - < 0.3: Weak/choppy (use tight targets)
        - 0.3-0.7: Moderate
        - > 0.7: Strong trend (use wide targets)
        
        Based on ADX-like logic: Directional Movement vs Total Range
        """
        try:
            if len(candles) < period + 1:
                return None
            
            recent = candles[-(period+1):]
            
            # Calculate directional movement
            dm_plus = 0
            dm_minus = 0
            true_range_sum = 0
            
            for i in range(1, len(recent)):
                prev = recent[i-1]
                curr = recent[i]
                
                if curr.high is None or curr.low is None or prev.close is None:
                    continue
                
                # Directional movement
                up_move = curr.high - prev.high
                down_move = prev.low - curr.low
                
                if up_move > down_move and up_move > 0:
                    dm_plus += up_move
                elif down_move > up_move and down_move > 0:
                    dm_minus += down_move
                
                # True range
                tr = max(
                    curr.high - curr.low,
                    abs(curr.high - prev.close),
                    abs(curr.low - prev.close)
                )
                true_range_sum += tr
            
            if true_range_sum == 0:
                return 0.0
            
            # Trend strength = dominant direction / total range
            dominant_dm = max(dm_plus, dm_minus)
            trend_strength = dominant_dm / true_range_sum
            
            # Normalize to 0-1 range
            trend_strength = min(1.0, trend_strength)
            
            return trend_strength
            
        except Exception as e:
            logger.error(f"Error calculating trend strength: {e}")
            return None

            return cvd
            
        except Exception as e:
            logger.error(f"Error calculating CVD: {e}")
            return None
