import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
import aiohttp
import numpy as np
import pandas as pd
from websockets.client import connect
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

# Constants
SYMBOL = "BTCUSDT"
BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"
BYBIT_REST_URL = "https://api.bybit.com/v5/market/kline"

class MarketState:
    def __init__(self):
        self.price = 0.0
        self.orderbook = {"bids": [], "asks": []}
        self.trades = deque(maxlen=1000)  # Keep last 1000 trades for CVD
        self.candles_1m = pd.DataFrame()
        self.candles_5m = pd.DataFrame()
        self.candles_15m = pd.DataFrame()
        self.regime = "UNCLEAR"
        self.trends = {"1m": "NEUTRAL", "5m": "NEUTRAL", "15m": "NEUTRAL"}
        self.gates_passed = False
        self.indicators = {
            "obi": 0.0,
            "cvd_1m": 0.0,
            "cvd_5m": 0.0,
            "atr": 0.0,
            "spread": 0.0,
            "depth": 0.0
        }
        self.is_warmed_up = False
        self.warmup_progress = 0
        self.last_update = 0
        self.backfill_error = False

class SignalState:
    def __init__(self):
        self.status = "IDLE"  # IDLE, FORMING, ACTIVE
        self.forming_since = 0
        self.active_until = 0
        self.cooldown_until = 0
        self.current_signal = None  # Dict with details
        self.history = []

class Engine:
    def __init__(self, telegram_bot=None):
        self.state = MarketState()
        self.signal_state = SignalState()
        self.telegram = telegram_bot
        self.ws_connected = False
        self.last_trade_time = 0
        self.running = False
        self.current_1m_candle = None

    async def start(self):
        self.running = True
        # Start Backfill with retry
        asyncio.create_task(self.backfill_loop())
        
        # Start WS Loop
        asyncio.create_task(self.ws_loop())
        
        # Start Processing Loop (1s interval)
        asyncio.create_task(self.processing_loop())

    async def backfill_loop(self):
        retry_delay = 5
        while self.running and not self.state.is_warmed_up:
            try:
                await self.backfill_candles()
                if self.state.is_warmed_up:
                    self.state.backfill_error = False
                    break
            except Exception as e:
                logger.error(f"Backfill loop error: {e}")
                self.state.backfill_error = True
            
            logger.info(f"Retrying backfill in {retry_delay}s...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60) # Cap at 60s

    async def backfill_candles(self):
        logger.info("Starting backfill...")
        # Try multiple endpoints or mirrors if possible, but here we just retry standard
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession(headers=headers) as session:
            # 1m candles (need 60)
            c1m = await self.fetch_kline(session, 1, 100)
            if c1m.empty: raise Exception("Failed to fetch 1m candles")
            self.state.candles_1m = c1m
            self.state.warmup_progress = 33
            
            # 5m candles (need 20)
            c5m = await self.fetch_kline(session, 5, 50)
            if c5m.empty: raise Exception("Failed to fetch 5m candles")
            self.state.candles_5m = c5m
            self.state.warmup_progress = 66
            
            # 15m candles (need 8)
            c15m = await self.fetch_kline(session, 15, 20)
            if c15m.empty: raise Exception("Failed to fetch 15m candles")
            self.state.candles_15m = c15m
            self.state.warmup_progress = 100
        
        self.state.is_warmed_up = True
        logger.info("Backfill complete.")

    async def fetch_kline(self, session, interval, limit):
        # Using bybit.com. If blocked, the loop will retry. 
        # In a real deployed env, might need a proxy or different mirror.
        params = {
            "category": "linear",
            "symbol": SYMBOL,
            "interval": str(interval),
            "limit": limit
        }
        try:
            async with session.get(BYBIT_REST_URL, params=params, timeout=5) as resp:
                if resp.status != 200:
                    logger.warning(f"Backfill HTTP {resp.status}")
                    return pd.DataFrame()
                    
                data = await resp.json()
                if data['retCode'] == 0:
                    df = pd.DataFrame(data['result']['list'], columns=['startTime', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
                    df = df.astype(float)
                    df['startTime'] = pd.to_datetime(df['startTime'], unit='ms')
                    df = df.sort_values('startTime').reset_index(drop=True)
                    # Calculate EMAs
                    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
                    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
                    
                    if interval == 5:
                        # Ensure we have enough data for ATR (14 periods)
                        df['tr'] = np.maximum(
                            df['high'] - df['low'],
                            np.maximum(
                                abs(df['high'] - df['close'].shift(1)),
                                abs(df['low'] - df['close'].shift(1))
                            )
                        )
                        df['atr'] = df['tr'].rolling(window=14).mean()
                    return df
        except Exception as e:
            logger.error(f"Fetch kline error: {e}")
        return pd.DataFrame()

    async def ws_loop(self):
        while self.running:
            try:
                async with connect(BYBIT_WS_URL) as websocket:
                    self.ws_connected = True
                    logger.info("Connected to Bybit WS")
                    
                    await websocket.send(json.dumps({
                        "op": "subscribe",
                        "args": [
                            f"orderbook.50.{SYMBOL}",
                            f"publicTrade.{SYMBOL}",
                            f"tickers.{SYMBOL}"
                        ]
                    }))

                    while True:
                        msg = await websocket.recv()
                        data = json.loads(msg)
                        self.handle_ws_message(data)
            except Exception as e:
                self.ws_connected = False
                logger.error(f"WS Error: {e}")
                await asyncio.sleep(5)

    def handle_ws_message(self, data):
        topic = data.get('topic', '')
        ts = time.time()
        self.state.last_update = ts

        if 'orderbook' in topic:
            type_ = data.get('type')
            if type_ == 'snapshot':
                self.state.orderbook = {
                    "bids": [[float(x[0]), float(x[1])] for x in data['data']['b']],
                    "asks": [[float(x[0]), float(x[1])] for x in data['data']['a']]
                }
            elif type_ == 'delta':
                for b in data['data']['b']:
                    price, size = float(b[0]), float(b[1])
                    found = False
                    for i, existing in enumerate(self.state.orderbook['bids']):
                        if existing[0] == price:
                            if size == 0:
                                self.state.orderbook['bids'].pop(i)
                            else:
                                self.state.orderbook['bids'][i][1] = size
                            found = True
                            break
                    if not found and size > 0:
                        self.state.orderbook['bids'].append([price, size])
                        self.state.orderbook['bids'].sort(key=lambda x: x[0], reverse=True)
                        self.state.orderbook['bids'] = self.state.orderbook['bids'][:50]

                for a in data['data']['a']:
                    price, size = float(a[0]), float(a[1])
                    found = False
                    for i, existing in enumerate(self.state.orderbook['asks']):
                        if existing[0] == price:
                            if size == 0:
                                self.state.orderbook['asks'].pop(i)
                            else:
                                self.state.orderbook['asks'][i][1] = size
                            found = True
                            break
                    if not found and size > 0:
                        self.state.orderbook['asks'].append([price, size])
                        self.state.orderbook['asks'].sort(key=lambda x: x[0])
                        self.state.orderbook['asks'] = self.state.orderbook['asks'][:50]

            self.calculate_obi()

        elif 'publicTrade' in topic:
            for t in data['data']:
                price = float(t['p'])
                size = float(t['v'])
                side = t['S']
                self.state.price = price
                self.state.trades.append({'price': price, 'size': size, 'side': side, 'time': ts})
                self.update_candle(price, size, ts)

    def update_candle(self, price, size, ts):
        current_min = int(ts // 60) * 60
        
        if self.current_1m_candle is None or self.current_1m_candle['startTime'] != current_min:
            if self.current_1m_candle:
                self.finalize_candle(self.current_1m_candle)
            
            self.current_1m_candle = {
                'startTime': current_min,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': size
            }
        else:
            c = self.current_1m_candle
            c['high'] = max(c['high'], price)
            c['low'] = min(c['low'], price)
            c['close'] = price
            c['volume'] += size

    def finalize_candle(self, candle):
        row = pd.DataFrame([candle])
        row['startTime'] = pd.to_datetime(row['startTime'], unit='s')
        
        self.state.candles_1m = pd.concat([self.state.candles_1m, row]).tail(100)
        self.state.candles_1m['ema20'] = self.state.candles_1m['close'].ewm(span=20, adjust=False).mean()
        self.state.candles_1m['ema50'] = self.state.candles_1m['close'].ewm(span=50, adjust=False).mean()

        self.resample_candles()

    def resample_candles(self):
        if len(self.state.candles_1m) > 0:
            df = self.state.candles_1m.set_index('startTime')
            
            # 5m
            c5 = df.resample('5min').agg({
                'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
            }).dropna()
            c5['ema20'] = c5['close'].ewm(span=20, adjust=False).mean()
            c5['ema50'] = c5['close'].ewm(span=50, adjust=False).mean()
            c5['tr'] = np.maximum(
                c5['high'] - c5['low'],
                np.maximum(
                    abs(c5['high'] - c5['close'].shift(1)),
                    abs(c5['low'] - c5['close'].shift(1))
                )
            )
            c5['atr'] = c5['tr'].rolling(window=14).mean()
            self.state.candles_5m = c5.reset_index()

            # 15m
            c15 = df.resample('15min').agg({
                'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
            }).dropna()
            c15['ema20'] = c15['close'].ewm(span=20, adjust=False).mean()
            c15['ema50'] = c15['close'].ewm(span=50, adjust=False).mean()
            self.state.candles_15m = c15.reset_index()

    def calculate_obi(self):
        if not self.state.orderbook['bids'] or not self.state.orderbook['asks']:
            return
        
        bids = self.state.orderbook['bids'][:10]
        asks = self.state.orderbook['asks'][:10]
        
        bid_vol = sum(b[1] for b in bids)
        ask_vol = sum(a[1] for a in asks)
        total = bid_vol + ask_vol
        
        raw_obi = (bid_vol - ask_vol) / total if total > 0 else 0
        self.state.indicators['obi'] = (0.3 * raw_obi) + (0.7 * self.state.indicators.get('obi', 0))

        # Gate Checks
        best_bid = self.state.orderbook['bids'][0][0]
        best_ask = self.state.orderbook['asks'][0][0]
        # Spread in bps: (Ask - Bid) / Bid * 10000
        spread_bps = (best_ask - best_bid) / best_bid * 10000 
        self.state.indicators['spread'] = spread_bps
        
        bid_val = sum(b[0] * b[1] for b in bids)
        ask_val = sum(a[0] * a[1] for a in asks)
        min_depth = min(bid_val, ask_val)
        self.state.indicators['depth'] = min_depth

    def calculate_cvd(self):
        now = time.time()
        trades_list = list(self.state.trades)
        
        # 1m
        buy_vol_1m = sum(t['size'] for t in trades_list if t['side'] == 'Buy' and t['time'] > now - 60)
        sell_vol_1m = sum(t['size'] for t in trades_list if t['side'] == 'Sell' and t['time'] > now - 60)
        total_1m = buy_vol_1m + sell_vol_1m
        ratio_1m = (buy_vol_1m - sell_vol_1m) / total_1m if total_1m > 0 else 0
        
        # 5m
        buy_vol_5m = sum(t['size'] for t in trades_list if t['side'] == 'Buy' and t['time'] > now - 300)
        sell_vol_5m = sum(t['size'] for t in trades_list if t['side'] == 'Sell' and t['time'] > now - 300)
        total_5m = buy_vol_5m + sell_vol_5m
        ratio_5m = (buy_vol_5m - sell_vol_5m) / total_5m if total_5m > 0 else 0

        self.state.indicators['cvd_1m'] = (0.3 * ratio_1m) + (0.7 * self.state.indicators.get('cvd_1m', 0))
        self.state.indicators['cvd_5m'] = (0.3 * ratio_5m) + (0.7 * self.state.indicators.get('cvd_5m', 0))

    async def processing_loop(self):
        while self.running:
            await asyncio.sleep(1)
            
            # If not warmed up, we can't do indicators or regime properly
            if not self.state.is_warmed_up:
                continue
                
            if time.time() - self.state.last_update > 10:
                logger.warning("Data stale")
                self.state.regime = "UNCLEAR"
                continue

            self.calculate_cvd()
            self.determine_regime()
            self.check_gates()
            await self.manage_signals()

    def determine_regime(self):
        if len(self.state.candles_5m) < 2 or len(self.state.candles_15m) < 2:
            return

        c5 = self.state.candles_5m.iloc[-1]
        c15 = self.state.candles_15m.iloc[-1]
        
        slope_5 = c5['ema20'] - self.state.candles_5m.iloc[-2]['ema20']
        slope_15 = c15['ema20'] - self.state.candles_15m.iloc[-2]['ema20']

        # Determine Trends for frontend
        self.state.trends["5m"] = "BULL" if (c5['ema20'] > c5['ema50'] and slope_5 > 0) else "BEAR" if (c5['ema20'] < c5['ema50'] and slope_5 < 0) else "NEUTRAL"
        self.state.trends["15m"] = "BULL" if (c15['ema20'] > c15['ema50'] and slope_15 > 0) else "BEAR" if (c15['ema20'] < c15['ema50'] and slope_15 < 0) else "NEUTRAL"
        
        # 1m Trend (for pullback check)
        if not self.state.candles_1m.empty:
            c1 = self.state.candles_1m.iloc[-1]
            slope_1 = c1['ema20'] - self.state.candles_1m.iloc[-2]['ema20'] if len(self.state.candles_1m) > 1 else 0
            self.state.trends["1m"] = "BULL" if (c1['ema20'] > c1['ema50'] and slope_1 > 0) else "BEAR" if (c1['ema20'] < c1['ema50'] and slope_1 < 0) else "NEUTRAL"

        bull = self.state.trends["5m"] == "BULL" and self.state.trends["15m"] == "BULL"
        bear = self.state.trends["5m"] == "BEAR" and self.state.trends["15m"] == "BEAR"

        atr = c5['atr']
        if pd.isna(atr): atr = 0
        
        # Rolling baseline 20 periods
        if len(self.state.candles_5m) >= 20:
             atr_baseline = self.state.candles_5m['atr'].rolling(window=20).mean().iloc[-1]
             if pd.isna(atr_baseline): atr_baseline = atr
        else:
             atr_baseline = atr

        is_chaotic = (atr > 2 * atr_baseline) or (self.state.indicators['spread'] > 5)

        if is_chaotic:
            self.state.regime = "CHAOTIC"
        elif bull:
            self.state.regime = "TRENDING_BULL"
        elif bear:
            self.state.regime = "TRENDING_BEAR"
        else:
            self.state.regime = "RANGING"

    def check_gates(self):
        spread_ok = self.state.indicators['spread'] < 1.5
        depth_ok = self.state.indicators['depth'] > 250000
        self.state.gates_passed = spread_ok and depth_ok

    async def manage_signals(self):
        now = time.time()
        
        if self.signal_state.status == "ACTIVE":
            if now > self.signal_state.active_until:
                self.signal_state.status = "IDLE"
                self.signal_state.cooldown_until = now + 600
                self.signal_state.current_signal = None
            return 

        if now < self.signal_state.cooldown_until:
            return

        if not self.state.gates_passed or "TRENDING" not in self.state.regime:
            self.reset_forming()
            return

        is_long = self.state.regime == "TRENDING_BULL"
        
        cvd_ok = (self.state.indicators['cvd_5m'] > 0.15) if is_long else (self.state.indicators['cvd_5m'] < -0.15)
        
        if len(self.state.candles_1m) < 1: return
        last_price = self.state.price
        ema20_1m = self.state.candles_1m.iloc[-1]['ema20']
        dist_pct = abs(last_price - ema20_1m) / ema20_1m * 100
        pullback_ok = dist_pct < 0.3
        
        obi_ok = (self.state.indicators['obi'] > 0.12) if is_long else (self.state.indicators['obi'] < -0.12)
        
        ema50_1m = self.state.candles_1m.iloc[-1]['ema50']
        structure_hold = (last_price > ema50_1m) if is_long else (last_price < ema50_1m)

        if cvd_ok and pullback_ok and obi_ok and structure_hold:
            score = 30 
            score += 25 if cvd_ok else 0
            score += 20 if pullback_ok else 0
            score += 20 if obi_ok else 0
            score += 5
            
            if score > 70:
                if self.signal_state.status == "IDLE":
                    self.signal_state.status = "FORMING"
                    self.signal_state.forming_since = now
                    logger.info("Signal FORMING...")
                elif self.signal_state.status == "FORMING":
                    if now - self.signal_state.forming_since >= 30:
                        await self.activate_signal(is_long, score)
            else:
                self.reset_forming()
        else:
            self.reset_forming()

    def reset_forming(self):
        if self.signal_state.status == "FORMING":
            self.signal_state.status = "IDLE"
            self.signal_state.forming_since = 0

    async def activate_signal(self, is_long, score):
        self.signal_state.status = "ACTIVE"
        now = time.time()
        self.signal_state.active_until = now + 300 
        
        atr = self.state.candles_5m.iloc[-1]['atr']
        if pd.isna(atr) or atr == 0: atr = 100 # Fallback safety
        
        entry = self.state.price
        
        sl_dist = 1.5 * atr
        tp1_dist = 2 * atr
        tp2_dist = 3.5 * atr
        
        if is_long:
            sl = entry - sl_dist
            tp1 = entry + tp1_dist
            tp2 = entry + tp2_dist
        else:
            sl = entry + sl_dist
            tp1 = entry - tp1_dist
            tp2 = entry - tp2_dist
            
        signal = {
            "id": str(int(now)),
            "direction": "LONG" if is_long else "SHORT",
            "entry_min": round(entry * 0.9999, 2),
            "entry_max": round(entry * 1.0001, 2),
            "stop_loss": round(sl, 2),
            "tp1": round(tp1, 2),
            "tp2": round(tp2, 2),
            "sl_pct": round((abs(entry-sl)/entry)*100, 2),
            "tp1_pct": round((abs(entry-tp1)/entry)*100, 2),
            "tp2_pct": round((abs(entry-tp2)/entry)*100, 2),
            "rr_ratio": round(tp1_dist/sl_dist, 2),
            "confidence": score,
            "reasons": ["Structure Aligned", "CVD Strength", "OBI Support"],
            "timestamp": now
        }
        
        self.signal_state.current_signal = signal
        logger.info(f"Signal ACTIVATED: {signal}")
        
        if self.telegram:
            await self.telegram.send_signal(signal)
