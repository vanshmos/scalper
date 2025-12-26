import asyncio
import json
import logging
import time
import os
from collections import deque
from datetime import datetime, timezone, timedelta
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
CACHE_FILE = "/app/data/candle_cache.json"

class MarketState:
    def __init__(self):
        self.price = 0.0
        self.orderbook = {"bids": [], "asks": []}
        self.trades = deque(maxlen=1000)
        self.candles_1m = pd.DataFrame()
        self.candles_5m = pd.DataFrame()
        self.candles_15m = pd.DataFrame()
        self.regime = "UNCLEAR"
        self.trends = {"1m": "NEUTRAL", "5m": "NEUTRAL", "15m": "NEUTRAL"}
        self.gates_passed = False
        self.gate_state_depth = "FAIL"
        self.gate_state_spread = "FAIL"
        self.last_gate_change = 0
        
        self.indicators = {
            "obi": None,
            "cvd_1m": None,
            "cvd_5m": None,
            "atr": None,
            "rsi": None, # Added RSI
            "spread": None,
            "depth": None,
            "smoothed_depth": 0.0,
            "funding_rate": None,
            "open_interest": None,
            "oi_change_5m": None
        }
        self.oi_history = deque(maxlen=600) 
        self.is_warmed_up = False
        self.warmup_progress = 0
        self.last_update = 0
        self.backfill_error = False
        self.backfill_error_msg = "Live Build Mode"
        self.backfill_retries = 0
        self.backfill_failed_final = False
        self.funding_regime = "NEUTRAL"
        
        # Debug Stats
        self.ws_msg_count = 0
        self.ws_last_time = time.time()
        self.ws_rate = 0.0
        self.ws_status = "DISCONNECTED"

class SignalState:
    def __init__(self):
        self.status = "IDLE"  # IDLE, FORMING, ACTIVE
        self.forming_since = 0
        self.active_until = 0
        self.cooldown_until = 0
        self.current_signal = None 
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
        logger.info("Starting Engine...")
        
        # Load Cache
        self.load_cache()
        
        # Start WS Loop
        asyncio.create_task(self.ws_loop())
        
        # Start Processing Loop (1s interval)
        asyncio.create_task(self.processing_loop())

    def load_cache(self):
        if not os.path.exists(CACHE_FILE):
            logger.info("No candle cache found. Starting fresh.")
            return

        try:
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
            
            if not data: return

            df = pd.DataFrame(data)
            df['startTime'] = pd.to_datetime(df['startTime'])
            
            # Filter last 3 hours
            cutoff = datetime.now() - timedelta(hours=3)
            df = df[df['startTime'] > cutoff]
            
            if df.empty:
                logger.info("Cache found but data is too old.")
                return

            df = df.sort_values('startTime').reset_index(drop=True)
            self.state.candles_1m = df
            
            # Recalculate indicators
            self.state.candles_1m['ema20'] = self.state.candles_1m['close'].ewm(span=20, adjust=False).mean()
            self.state.candles_1m['ema50'] = self.state.candles_1m['close'].ewm(span=50, adjust=False).mean()
            
            self.resample_candles()
            
            count = len(self.state.candles_1m)
            logger.info(f"Loaded {count} candles from cache.")
            
            if count >= 50:
                self.state.is_warmed_up = True
                self.state.warmup_progress = 100
                logger.info("Engine warmed up from cache!")
            else:
                self.state.warmup_progress = int((count / 50) * 100)
                
        except Exception as e:
            logger.error(f"Failed to load cache: {e}")

    def save_cache(self):
        try:
            # Keep last 180 candles (3 hours)
            if self.state.candles_1m.empty: return
            
            df = self.state.candles_1m.tail(180).copy()
            # Convert timestamp to string for JSON
            df['startTime'] = df['startTime'].dt.strftime('%Y-%m-%d %H:%M:%S')
            # Select only OHLCV
            cols = ['startTime', 'open', 'high', 'low', 'close', 'volume']
            data = df[cols].to_dict(orient='records')
            
            with open(CACHE_FILE, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")

    async def ws_loop(self):
        while self.running:
            try:
                self.state.ws_status = "CONNECTING"
                logger.info(f"Connecting to WS: {BYBIT_WS_URL}")
                
                async with connect(BYBIT_WS_URL) as websocket:
                    self.ws_connected = True
                    self.state.ws_status = "CONNECTED"
                    logger.info("WS Connected Successfully")
                    
                    await websocket.send(json.dumps({
                        "op": "subscribe",
                        "args": [
                            f"orderbook.50.{SYMBOL}",
                            f"publicTrade.{SYMBOL}",
                            f"tickers.{SYMBOL}"
                        ]
                    }))

                    last_rate_update = time.time()
                    msg_count = 0

                    while True:
                        msg = await websocket.recv()
                        data = json.loads(msg)
                        self.handle_ws_message(data)
                        
                        # WS Rate Calc
                        msg_count += 1
                        now = time.time()
                        if now - last_rate_update >= 1.0:
                            self.state.ws_rate = msg_count / (now - last_rate_update)
                            msg_count = 0
                            last_rate_update = now

            except Exception as e:
                self.ws_connected = False
                self.state.ws_status = "DISCONNECTED"
                logger.error(f"WS Error: {e}")
                logger.info("WS Disconnected. Retrying in 5s...")
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
            
            if int(ts) % 10 == 0:
                 logger.info(f"Orderbook Levels: Bids={len(self.state.orderbook['bids'])}, Asks={len(self.state.orderbook['asks'])}")

            self.calculate_obi()

        elif 'publicTrade' in topic:
            for t in data['data']:
                price = float(t['p'])
                size = float(t['v'])
                side = t['S']
                self.state.price = price
                self.state.trades.append({'price': price, 'size': size, 'side': side, 'time': ts})
                self.update_candle(price, size, ts)
        
        elif 'tickers' in topic:
            if 'data' in data:
                d = data['data']
                if 'fundingRate' in d:
                    try:
                        self.state.indicators['funding_rate'] = float(d['fundingRate']) * 100 
                    except: pass
                
                if 'openInterest' in d:
                    try:
                        if 'openInterestValue' in d:
                            self.state.indicators['open_interest'] = float(d['openInterestValue'])
                        else:
                            oi_size = float(d['openInterest'])
                            self.state.indicators['open_interest'] = oi_size * self.state.price
                    except: pass


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
        
        self.state.candles_1m = pd.concat([self.state.candles_1m, row]).tail(180) # Keep 3 hours in memory too
        self.state.candles_1m['ema20'] = self.state.candles_1m['close'].ewm(span=20, adjust=False).mean()
        self.state.candles_1m['ema50'] = self.state.candles_1m['close'].ewm(span=50, adjust=False).mean()

        self.save_cache() # SAVE TO DISK
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
            c5['atr'] = c5['tr'].rolling(window=14, min_periods=1).mean()
            
            # RSI Calculation
            delta = c5['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            c5['rsi'] = 100 - (100 / (1 + rs))
            
            self.state.candles_5m = c5.reset_index()
            
            if not c5.empty:
                last = c5.iloc[-1]
                self.state.indicators['rsi'] = last['rsi'] if not pd.isna(last['rsi']) else None
                logger.info(f"5m Candle: C={last['close']}, ATR={last['atr']}, RSI={self.state.indicators['rsi']}")

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
        current_obi = self.state.indicators.get('obi')
        if current_obi is None: current_obi = 0.0
        self.state.indicators['obi'] = (0.3 * raw_obi) + (0.7 * current_obi)

        # Gate Checks
        best_bid = self.state.orderbook['bids'][0][0]
        best_ask = self.state.orderbook['asks'][0][0]
        mid_price = (best_ask + best_bid) / 2
        spread_bps = (best_ask - best_bid) / mid_price * 10000 
        self.state.indicators['spread'] = spread_bps
        
        if int(time.time()) % 10 == 0:
            logger.info(f"Spread Calc: Bid={best_bid}, Ask={best_ask}, Spread={spread_bps:.4f} bps")
        
        bid_val = sum(b[0] * b[1] for b in bids)
        ask_val = sum(a[0] * a[1] for a in asks)
        min_depth = min(bid_val, ask_val)
        self.state.indicators['depth'] = min_depth
        
        current_smoothed = self.state.indicators.get('smoothed_depth', 0.0)
        smoothed = (0.1 * min_depth) + (0.9 * current_smoothed)
        self.state.indicators['smoothed_depth'] = smoothed

    def calculate_cvd(self):
        now = time.time()
        trades_list = list(self.state.trades)
        
        buy_vol_1m = sum(t['size'] for t in trades_list if t['side'] == 'Buy' and t['time'] > now - 60)
        sell_vol_1m = sum(t['size'] for t in trades_list if t['side'] == 'Sell' and t['time'] > now - 60)
        total_1m = buy_vol_1m + sell_vol_1m
        ratio_1m = (buy_vol_1m - sell_vol_1m) / total_1m if total_1m > 0 else 0
        
        buy_vol_5m = sum(t['size'] for t in trades_list if t['side'] == 'Buy' and t['time'] > now - 300)
        sell_vol_5m = sum(t['size'] for t in trades_list if t['side'] == 'Sell' and t['time'] > now - 300)
        total_5m = buy_vol_5m + sell_vol_5m
        ratio_5m = (buy_vol_5m - sell_vol_5m) / total_5m if total_5m > 0 else 0

        current_cvd_1m = self.state.indicators.get('cvd_1m')
        if current_cvd_1m is None: current_cvd_1m = 0.0
        
        current_cvd_5m = self.state.indicators.get('cvd_5m')
        if current_cvd_5m is None: current_cvd_5m = 0.0

        self.state.indicators['cvd_1m'] = (0.3 * ratio_1m) + (0.7 * current_cvd_1m)
        self.state.indicators['cvd_5m'] = (0.3 * ratio_5m) + (0.7 * current_cvd_5m)
        
        if int(now) % 10 == 0:
            logger.info(f"CVD Calc: Trades={len(trades_list)}, Smoothed1m={self.state.indicators['cvd_1m']:.3f}")

    def update_oi_change(self):
        now = time.time()
        current_oi = self.state.indicators['open_interest']
        if current_oi is None: return

        self.state.oi_history.append((now, current_oi))
        while self.state.oi_history and self.state.oi_history[0][0] < now - 300:
            self.state.oi_history.popleft()
            
        if len(self.state.oi_history) > 1:
            old_oi = self.state.oi_history[0][1]
            if old_oi > 0:
                change = (current_oi - old_oi) / old_oi * 100
                self.state.indicators['oi_change_5m'] = change

    async def processing_loop(self):
        while self.running:
            await asyncio.sleep(1)
            
            if not self.state.is_warmed_up:
                count_1m = len(self.state.candles_1m)
                progress = min(100, int((count_1m / 50) * 100)) # 50 candles target
                self.state.warmup_progress = progress
                
                if count_1m >= 50:
                    self.state.is_warmed_up = True
                    logger.info("Warmup Complete!")
            
            if time.time() - self.state.last_update > 10:
                logger.warning("Data stale")
                self.state.regime = "UNCLEAR"
                continue

            self.update_oi_change()
            self.calculate_cvd()
            self.determine_regime()
            self.check_gates()
            
            if self.state.is_warmed_up:
                await self.manage_signals()

    def determine_regime(self):
        if len(self.state.candles_5m) < 2 or len(self.state.candles_15m) < 2:
            return

        c5 = self.state.candles_5m.iloc[-1]
        c15 = self.state.candles_15m.iloc[-1]
        
        slope_5 = c5['ema20'] - self.state.candles_5m.iloc[-2]['ema20']
        slope_15 = c15['ema20'] - self.state.candles_15m.iloc[-2]['ema20']

        self.state.trends["5m"] = "BULL" if (c5['ema20'] > c5['ema50'] and slope_5 > 0) else "BEAR" if (c5['ema20'] < c5['ema50'] and slope_5 < 0) else "NEUTRAL"
        self.state.trends["15m"] = "BULL" if (c15['ema20'] > c15['ema50'] and slope_15 > 0) else "BEAR" if (c15['ema20'] < c15['ema50'] and slope_15 < 0) else "NEUTRAL"
        
        if not self.state.candles_1m.empty:
            c1 = self.state.candles_1m.iloc[-1]
            slope_1 = c1['ema20'] - self.state.candles_1m.iloc[-2]['ema20'] if len(self.state.candles_1m) > 1 else 0
            self.state.trends["1m"] = "BULL" if (c1['ema20'] > c1['ema50'] and slope_1 > 0) else "BEAR" if (c1['ema20'] < c1['ema50'] and slope_1 < 0) else "NEUTRAL"

        bull = self.state.trends["5m"] == "BULL" and self.state.trends["15m"] == "BULL"
        bear = self.state.trends["5m"] == "BEAR" and self.state.trends["15m"] == "BEAR"

        atr = c5['atr']
        if pd.isna(atr): atr = 0
        self.state.indicators['atr'] = atr
        
        if len(self.state.candles_5m) >= 20:
             atr_baseline = self.state.candles_5m['atr'].rolling(window=20).mean().iloc[-1]
             if pd.isna(atr_baseline): atr_baseline = atr
        else:
             atr_baseline = atr

        spread = self.state.indicators.get('spread')
        if spread is None: spread = 0.0
        
        is_chaotic = (atr > 2 * atr_baseline) or (spread > 5)

        funding = self.state.indicators.get('funding_rate')
        if funding:
            if funding > 0.03:
                self.state.funding_regime = "EXTREME_LONG_FUNDING"
            elif funding < -0.02:
                self.state.funding_regime = "EXTREME_SHORT_FUNDING"
            else:
                self.state.funding_regime = "NEUTRAL"

        if is_chaotic:
            self.state.regime = "CHAOTIC"
        elif bull:
            self.state.regime = "TRENDING_BULL"
        elif bear:
            self.state.regime = "TRENDING_BEAR"
        else:
            self.state.regime = "RANGING"

    def check_gates(self):
        now = time.time()
        spread = self.state.indicators.get('spread')
        depth = self.state.indicators.get('smoothed_depth') # Use smoothed
        
        if spread is None or depth is None:
            return

        # Hysteresis for Depth
        # PASS if > 50k. FAIL if < 40k.
        if self.state.gate_state_depth == "PASS":
            if depth < 40000:
                if self.should_flip_gate(now):
                    self.state.gate_state_depth = "FAIL"
        else: # FAIL
            if depth > 50000:
                if self.should_flip_gate(now):
                    self.state.gate_state_depth = "PASS"

        # Hysteresis for Spread
        # PASS if < 1.5. FAIL if > 2.0.
        if self.state.gate_state_spread == "PASS":
            if spread > 2.0:
                if self.should_flip_gate(now):
                    self.state.gate_state_spread = "FAIL"
        else: # FAIL
            if spread < 1.5:
                if self.should_flip_gate(now):
                    self.state.gate_state_spread = "PASS"

        self.state.gates_passed = (self.state.gate_state_depth == "PASS") and (self.state.gate_state_spread == "PASS")

    def should_flip_gate(self, now):
        # 3 second debounce
        if now - self.state.last_gate_change > 3:
            self.state.last_gate_change = now
            return True
        return False

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
        
        cvd_5m = self.state.indicators.get('cvd_5m')
        obi = self.state.indicators.get('obi')
        if cvd_5m is None or obi is None: return

        cvd_ok = (cvd_5m > 0.15) if is_long else (cvd_5m < -0.15)
        
        if len(self.state.candles_1m) < 1: return
        last_price = self.state.price
        ema20_1m = self.state.candles_1m.iloc[-1]['ema20']
        dist_pct = abs(last_price - ema20_1m) / ema20_1m * 100
        pullback_ok = dist_pct < 0.3
        
        obi_ok = (obi > 0.12) if is_long else (obi < -0.12)
        
        ema50_1m = self.state.candles_1m.iloc[-1]['ema50']
        structure_hold = (last_price > ema50_1m) if is_long else (last_price < ema50_1m)

        if cvd_ok and pullback_ok and obi_ok and structure_hold:
            score = 30 
            score += 25 if cvd_ok else 0
            score += 20 if pullback_ok else 0
            score += 20 if obi_ok else 0
            score += 5

            funding = self.state.indicators.get('funding_rate')
            reasons = ["Structure Aligned", "CVD Strength", "OBI Support"]
            
            if funding:
                if is_long:
                    if funding < 0:
                        score += 5
                        reasons.append(f"Funding Supportive ({funding:.3f}%)")
                    if funding > 0.03:
                        score -= 5
                        reasons.append(f"Caution: Extreme Long Funding ({funding:.3f}%)")
                else: 
                    if funding > 0:
                        score += 5
                        reasons.append(f"Funding Supportive ({funding:.3f}%)")
                    if funding < -0.02:
                        score -= 5
                        reasons.append(f"Caution: Extreme Short Funding ({funding:.3f}%)")
            
            rsi = self.state.indicators.get('rsi')
            if rsi:
                if is_long and rsi > 75:
                    score -= 15
                    reasons.append(f"RSI Overbought ({rsi:.1f})")
                if not is_long and rsi < 25:
                    score -= 15
                    reasons.append(f"RSI Oversold ({rsi:.1f})")

            if score > 70:
                if self.signal_state.status == "IDLE":
                    self.signal_state.status = "FORMING"
                    self.signal_state.forming_since = now
                    logger.info("Signal FORMING...")
                elif self.signal_state.status == "FORMING":
                    if now - self.signal_state.forming_since >= 30:
                        await self.activate_signal(is_long, score, reasons)
            else:
                self.reset_forming()
        else:
            self.reset_forming()

    def reset_forming(self):
        if self.signal_state.status == "FORMING":
            self.signal_state.status = "IDLE"
            self.signal_state.forming_since = 0

    async def activate_signal(self, is_long, score, reasons):
        self.signal_state.status = "ACTIVE"
        now = time.time()
        self.signal_state.active_until = now + 300 
        
        atr = self.state.candles_5m.iloc[-1]['atr']
        if pd.isna(atr) or atr == 0: atr = 100 
        
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
            "reasons": reasons,
            "timestamp": now
        }
        
        self.signal_state.current_signal = signal
        logger.info(f"Signal ACTIVATED: {signal}")
        
        if self.telegram:
            await self.telegram.send_signal(signal)
