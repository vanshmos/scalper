import requests
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class OKXRestClient:
    """OKX REST client for historical data backfill"""
    
    def __init__(self):
        self.base_url = "https://www.okx.com"
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json'
        })
    
    def get_candles(self, symbol: str, timeframe: str, limit: int = 100) -> Optional[List[Dict]]:
        """
        Fetch historical candles
        
        Args:
            symbol: e.g. "BTC-USDT-SWAP"
            timeframe: "1m", "5m", etc.
            limit: max 100 for most timeframes
            
        Returns:
            List of candles in OKX format: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        """
        try:
            url = f"{self.base_url}/api/v5/market/candles"
            params = {
                "instId": symbol,
                "bar": timeframe,
                "limit": limit
            }
            
            response = self.session.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == '0':
                    candles = data.get('data', [])
                    logger.info(f"Fetched {len(candles)} {timeframe} candles for {symbol}")
                    return candles
                else:
                    logger.error(f"OKX API error: {data.get('msg', 'Unknown error')}")
                    return None
            else:
                logger.error(f"HTTP error {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching candles: {e}")
            return None
    
    def get_funding_rate(self, symbol: str) -> Optional[Dict]:
        """
        Fetch current funding rate
        
        Returns:
            Dict with fundingRate, fundingTime, nextFundingRate, nextFundingTime
        """
        try:
            url = f"{self.base_url}/api/v5/public/funding-rate"
            params = {"instId": symbol}
            
            response = self.session.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == '0' and data.get('data'):
                    return data['data'][0]
                    
        except Exception as e:
            logger.error(f"Error fetching funding rate: {e}")
            
        return None
    
    def get_open_interest(self, symbol: str) -> Optional[Dict]:
        """Fetch current open interest"""
        try:
            url = f"{self.base_url}/api/v5/public/open-interest"
            params = {
                "instType": "SWAP",
                "instId": symbol
            }
            
            response = self.session.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == '0' and data.get('data'):
                    return data['data'][0]
                    
        except Exception as e:
            logger.error(f"Error fetching open interest: {e}")
            
        return None
