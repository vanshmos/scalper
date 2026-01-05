import json
import logging
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional
from pathlib import Path
import asyncio

logger = logging.getLogger(__name__)

class Candle:
    def __init__(self, timestamp: int, timeframe: str):
        self.timestamp = timestamp  # Start of candle in seconds
        self.timeframe = timeframe
        self.open: Optional[float] = None
        self.high: Optional[float] = None
        self.low: Optional[float] = None
        self.close: Optional[float] = None
        self.volume = 0.0
        self.vol_ma20: Optional[float] = None  # 20-period volume moving average
        
    def update(self, price: float, volume: float):
        """Update candle with new trade data"""
        if self.open is None:
            self.open = price
        self.high = price if self.high is None else max(self.high, price)
        self.low = price if self.low is None else min(self.low, price)
        self.close = price
        self.volume += volume
    
    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp,
            'timeframe': self.timeframe,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'vol_ma20': self.vol_ma20
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        candle = cls(data['timestamp'], data['timeframe'])
        candle.open = data.get('open')
        candle.high = data.get('high')
        candle.low = data.get('low')
        candle.close = data.get('close')
        candle.volume = data.get('volume', 0.0)
        candle.vol_ma20 = data.get('vol_ma20')
        return candle


class CandleBuilder:
    def __init__(self, symbol: str, data_file: str = None):
        self.symbol = symbol
        if data_file is None:
            data_file = f"/app/backend/candles_{symbol.lower()}.json"
        self.data_file = Path(data_file)
        self.candles_1m: List[Candle] = []
        self.candles_5m: List[Candle] = []
        self.candles_15m: List[Candle] = []
        self.current_candle_1m: Optional[Candle] = None
        self.max_history_hours = 3
        self.last_save_time = 0
        self.save_interval = 60  # Save every 60 seconds
        
        # Load existing data
        self.load_from_file()
        
        # Fetch historical backfill if needed (trigger if less than 100 candles)
        if len(self.candles_1m) < 100:
            self.fetch_historical_backfill()
    
    def load_from_file(self):
        """Load candles from JSON file on startup"""
        try:
            if self.data_file.exists():
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    
                self.candles_1m = [Candle.from_dict(c) for c in data.get('candles_1m', [])]
                self.candles_5m = [Candle.from_dict(c) for c in data.get('candles_5m', [])]
                self.candles_15m = [Candle.from_dict(c) for c in data.get('candles_15m', [])]
                
                logger.info(f"Loaded {len(self.candles_1m)} 1m candles, {len(self.candles_5m)} 5m candles, {len(self.candles_15m)} 15m candles for {self.symbol}")
        except Exception as e:
            logger.error(f"Error loading candles from file for {self.symbol}: {e}")
    
    def fetch_historical_backfill(self):
        """Fetch historical 1m candles from OKX REST API (runs once on startup)"""
        try:
            logger.info(f"Attempting historical backfill from OKX REST API for {self.symbol}...")
            
            # OKX REST API endpoint for current market candles
            url = "https://www.okx.com/api/v5/market/candles"
            params = {
                "instId": f"{self.symbol}-USDT-SWAP",
                "bar": "1m",
                "limit": "200"  # Get 200 candles (3.3 hours of data)
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('code') == '0':
                    candles_data = data.get('data', [])
                    
                    # OKX returns: [timestamp_ms, open, high, low, close, volume, volCcy, volCcyQuote, confirm]
                    # Process in reverse (oldest first)
                    for candle_data in reversed(candles_data):
                        timestamp = int(candle_data[0]) // 1000  # Convert ms to seconds
                        
                        candle = Candle(timestamp, '1m')
                        candle.open = float(candle_data[1])
                        candle.high = float(candle_data[2])
                        candle.low = float(candle_data[3])
                        candle.close = float(candle_data[4])
                        candle.volume = float(candle_data[5])
                        
                        self.candles_1m.append(candle)
                    
                    # Trim to max history
                    self._trim_history()
                    
                    # Resample to 5m and 15m
                    self._resample_candles()
                    
                    # Save to file
                    self.save_to_file()
                    
                    logger.info(f"Successfully backfilled {len(candles_data)} 1m candles from REST API for {self.symbol} (3.3hrs history)")
                else:
                    logger.warning(f"OKX REST API returned error code: {data.get('code')} for {self.symbol}")
            elif response.status_code == 403:
                logger.warning(f"OKX REST API blocked (403) for {self.symbol} - cloud IP restriction. Falling back to live stream warmup.")
            else:
                logger.warning(f"OKX REST API returned status {response.status_code} for {self.symbol}")
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch historical data from REST API for {self.symbol}: {e}. Falling back to live stream warmup.")
        except Exception as e:
            logger.error(f"Error during historical backfill for {self.symbol}: {e}")
    
    def save_to_file(self):
        """Save candles to JSON file"""
        try:
            data = {
                'candles_1m': [c.to_dict() for c in self.candles_1m],
                'candles_5m': [c.to_dict() for c in self.candles_5m],
                'candles_15m': [c.to_dict() for c in self.candles_15m],
                'last_updated': datetime.now(timezone.utc).isoformat()
            }
            
            # Write to temp file first, then rename for atomic write
            temp_file = self.data_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            temp_file.rename(self.data_file)
            
            logger.info(f"Saved candles to {self.data_file}")
        except Exception as e:
            logger.error(f"Error saving candles to file: {e}")
    
    async def on_trade(self, trade: dict):
        """Process incoming trade and update candles"""
        try:
            # OKX field mapping: px=price, sz=size, side=side, ts=timestamp
            price = float(trade.get('px', 0))
            volume = float(trade.get('sz', 0))
            timestamp_ms = int(trade.get('ts', 0))
            timestamp = timestamp_ms // 1000
            
            if price == 0 or timestamp == 0:
                return
            
            # Get current minute timestamp
            minute_timestamp = (timestamp // 60) * 60
            
            # Create new candle if needed
            if self.current_candle_1m is None or self.current_candle_1m.timestamp != minute_timestamp:
                # Save previous candle if it exists
                if self.current_candle_1m is not None:
                    self.candles_1m.append(self.current_candle_1m)
                    self._trim_history()
                    self._resample_candles()
                    
                    # Save to file periodically
                    current_time = asyncio.get_event_loop().time()
                    if current_time - self.last_save_time >= self.save_interval:
                        self.save_to_file()
                        self.last_save_time = current_time
                
                # Start new candle
                self.current_candle_1m = Candle(minute_timestamp, '1m')
            
            # Update current candle
            self.current_candle_1m.update(price, volume)
            
        except Exception as e:
            logger.error(f"Error processing trade: {e}")
    
    def _trim_history(self):
        """Keep only last 3 hours of data"""
        max_candles = self.max_history_hours * 60
        
        if len(self.candles_1m) > max_candles:
            self.candles_1m = self.candles_1m[-max_candles:]
        
        max_candles_5m = self.max_history_hours * 12
        if len(self.candles_5m) > max_candles_5m:
            self.candles_5m = self.candles_5m[-max_candles_5m:]
        
        max_candles_15m = self.max_history_hours * 4
        if len(self.candles_15m) > max_candles_15m:
            self.candles_15m = self.candles_15m[-max_candles_15m:]
    
    def _resample_candles(self):
        """Resample 1m candles into 5m and 15m candles"""
        try:
            # Include current candle in resampling
            all_1m_candles = self.candles_1m.copy()
            if self.current_candle_1m is not None:
                all_1m_candles.append(self.current_candle_1m)
            
            logger.debug(f"Resampling with {len(all_1m_candles)} 1m candles (completed: {len(self.candles_1m)}, current: {1 if self.current_candle_1m else 0})")
            
            # Resample to 5m
            self.candles_5m = self._resample_to_timeframe(all_1m_candles, 5)
            logger.debug(f"Resampled to {len(self.candles_5m)} 5m candles")
            if len(self.candles_5m) > 0:
                logger.debug(f"Last 5m candle: timestamp={self.candles_5m[-1].timestamp}, close={self.candles_5m[-1].close}")
            
            # Resample to 15m
            self.candles_15m = self._resample_to_timeframe(all_1m_candles, 15)
            
        except Exception as e:
            logger.error(f"Error resampling candles: {e}")
    
    def _resample_to_timeframe(self, candles_1m: List[Candle], minutes: int) -> List[Candle]:
        """Resample 1m candles to higher timeframe"""
        if not candles_1m:
            return []
        
        resampled = []
        timeframe = f"{minutes}m"
        
        for candle_1m in candles_1m:
            # Calculate which higher timeframe candle this belongs to
            htf_timestamp = (candle_1m.timestamp // (minutes * 60)) * (minutes * 60)
            
            # Find or create higher timeframe candle
            if not resampled or resampled[-1].timestamp != htf_timestamp:
                htf_candle = Candle(htf_timestamp, timeframe)
                resampled.append(htf_candle)
            else:
                htf_candle = resampled[-1]
            
            # Update higher timeframe candle
            if candle_1m.open is not None:
                if htf_candle.open is None:
                    htf_candle.open = candle_1m.open
                if candle_1m.high is not None:
                    htf_candle.high = candle_1m.high if htf_candle.high is None else max(htf_candle.high, candle_1m.high)
                if candle_1m.low is not None:
                    htf_candle.low = candle_1m.low if htf_candle.low is None else min(htf_candle.low, candle_1m.low)
                htf_candle.close = candle_1m.close
                htf_candle.volume += candle_1m.volume
        
        return resampled
    
    def get_status(self) -> dict:
        """Get current candle builder status"""
        current_price = None
        if self.current_candle_1m and self.current_candle_1m.close is not None:
            current_price = self.current_candle_1m.close
        
        return {
            'candle_counts': {
                '1m': len(self.candles_1m) + (1 if self.current_candle_1m else 0),
                '5m': len(self.candles_5m),
                '15m': len(self.candles_15m)
            },
            'current_price': current_price
        }
