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
        
    def calculate_ema(self, candles: List[Candle], period: int) -> Optional[float]:
        """Calculate EMA for given period"""
        try:
            if len(candles) < period:
                return None
            
            # Get closing prices
            closes = [c.close for c in candles[-period:] if c.close is not None]
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
            
            return cvd
            
        except Exception as e:
            logger.error(f"Error calculating CVD: {e}")
            return None
