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
SYMBOL = "BTC-USD" # Coinbase uses Dash
COINBASE_WS_URL = "wss://ws-feed.exchange.coinbase.com"
CACHE_FILE = "/app/data/candle_cache.json"

class MarketState:
    def __init__(self):
        self.price = 0.0
        # Coinbase Orderbook: { "bids": {price: size}, "asks": {price: size} }
        # Using dict for O(1) updates
        self.orderbook = {"bids": {}, "asks": {}}
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
            "rsi": None, 
            "spread": None,
            "depth": None,
            "smoothed_depth": 0.0,
            "funding_rate": 0.01, # Coinbase has no perp funding in public spot feed
            "open_interest": 0,
            "oi_change_5m": 0,
            "ema20_1m": None,
            "ema50_1m": None
        }
        self.oi_history = deque(maxlen=600) 
        self.is_warmed_up = False
        self.warmup_progress = 0
        self.last_update = 0
        self.backfill_error = False
        self.backfill_error_msg = "Live Build Mode (Coinbase)"
        self.backfill_retries = 0
        self.backfill_failed_final = False
        self.funding_regime = "NEUTRAL"
        
        self.checklist = {}
        
        # Debug Stats
        self.ws_msg_count = 0
        self.ws_last_time = time.time()
        self.ws_rate = 0.0

class SignalState:
    def __init__(self):
        self.status = "IDLE"
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
        logger.info("Starting Engine in Live Build Mode (Coinbase)")
        self.load_cache()
        asyncio.create_task(self.ws_loop())
        asyncio.create_task(self.processing_loop())

    def load_cache(self):
        if not os.path.exists(CACHE_FILE): return
        try:
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
            if not data: return
            df = pd.DataFrame(data)
            df['startTime'] = pd.to_datetime(df['startTime'])
            df = df.sort_values('startTime').reset_index(drop=True)
            self.state.candles_1m = df
            
            self.state.candles_1m['ema20'] = self.state.candles_1m['close'].ewm(span=20, adjust=False).mean()
            self.state.candles_1m['ema50'] = self.state.candles_1m['close'].ewm(span=50, adjust=False).mean()
            if not self.state.candles_1m.empty:
                last = self.state.candles_1m.iloc[-1]
                self.state.indicators['ema20_1m'] = last['ema20']
                self.state.indicators['ema50_1m'] = last['ema50']
            
            self.resample_candles()
            if len(self.state.candles_1m) >= 50:
                self.state.is_warmed_up = True
                self.state.warmup_progress = 100
        except Exception as e:
            logger.error(f"Cache error: {e}")

    def save_cache(self):
        try:
            if self.state.candles_1m.empty: return
            df = self.state.candles_1m.tail(180).copy()
            df['startTime'] = df['startTime'].dt.strftime('%Y-%m-%d %H:%M:%S')
            data = df[['startTime','open','high','low','close','volume']].to_dict(orient='records')
            with open(CACHE_FILE, 'w') as f:
                json.dump(data, f)
        except: pass

    async def ws_loop(self):
        while self.running:
            try:
                # Set max_size to None (unlimited) for huge snapshots
                async with connect(COINBASE_WS_URL, max_size=None) as websocket:
                    self.ws_connected = True
                    logger.info("Connected to Coinbase WS")
                    
                    await websocket.send(json.dumps({
                        "type": "subscribe",
                        "product_ids": [SYMBOL],
                        "channels": ["level2", "matches", "ticker"]
                    }))

                    last_rate_update = time.time()
                    msg_count = 0

                    while True:
                        msg = await websocket.recv()
                        data = json.loads(msg)
                        self.handle_ws_message(data)
                        
                        msg_count += 1
                        now = time.time()
                        if now - last_rate_update >= 1.0:
                            self.state.ws_rate = msg_count / (now - last_rate_update)
                            msg_count = 0
                            last_rate_update = now

            except Exception as e:
                self.ws_connected = False
                logger.error(f"WS Error: {e}")
                await asyncio.sleep(5)

    def handle_ws_message(self, data):
        type_ = data.get('type')
        ts = time.time()
        self.state.last_update = ts

        if type_ == 'ticker':
            if 'price' in data:
                self.state.price = float(data['price'])

        elif type_ == 'snapshot':
            # {"bids": [["price", "size"]...], "asks": ...}
            self.state.orderbook = {
                "bids": {float(p): float(s) for p, s in data['bids']},
                "asks": {float(p): float(s) for p, s in data['asks']}
            }
            self.calculate_obi()

        elif type_ == 'l2update':
            # {"changes": [["side", "price", "size"]...]}
            for side, price_str, size_str in data['changes']:
                price = float(price_str)
                size = float(size_str)
                book_side = "bids" if side == "buy" else "asks"
                
                if size == 0:
                    if price in self.state.orderbook[book_side]:
                        del self.state.orderbook[book_side][price]
                else:
                    self.state.orderbook[book_side][price] = size
            
            # Recalc periodically to save CPU
            if int(ts * 10) % 5 == 0: # 2Hz
                self.calculate_obi()

        elif type_ == 'match':
            # {"size": "...", "price": "...", "side": "buy"/"sell"}
            price = float(data['price'])
            size = float(data['size'])
            side = 'Buy' if data['side'] == 'buy' else 'Sell' # Coinbase 'side' is the MAKER side?
            # Coinbase docs: "side": "buy" means the maker was a buy order? No.
            # "side": "buy" indicates a buy order matched a sell order. The AGGRESSOR is buy.
            # So side='buy' -> Price went UP (usually).
            # Let's map directly: side='buy' -> Buy, side='sell' -> Sell.
            
            self.state.price = price
            self.state.trades.append({'price': price, 'size': size, 'side': side, 'time': ts})
            self.update_candle(price, size, ts)

    def update_candle(self, price, size, ts):
        current_min = int(ts // 60) * 60
        if self.current_1m_candle is None or self.current_1m_candle['startTime'] != current_min:
            if self.current_1m_candle:
                self.finalize_candle(self.current_1m_candle)
            self.current_1m_candle = {
                'startTime': current_min, 'open': price, 'high': price, 'low': price, 'close': price, 'volume': size
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
        self.state.candles_1m = pd.concat([self.state.candles_1m, row]).tail(180)
        self.state.candles_1m['ema20'] = self.state.candles_1m['close'].ewm(span=20, adjust=False).mean()
        self.state.candles_1m['ema50'] = self.state.candles_1m['close'].ewm(span=50, adjust=False).mean()
        
        if not self.state.candles_1m.empty:
            self.state.indicators['ema20_1m'] = self.state.candles_1m.iloc[-1]['ema20']
            self.state.indicators['ema50_1m'] = self.state.candles_1m.iloc[-1]['ema50']
            
        self.save_cache()
        self.resample_candles()

    def resample_candles(self):
        if len(self.state.candles_1m) == 0: return
        df = self.state.candles_1m.set_index('startTime')
        
        c5 = df.resample('5min').agg({'open':'first', 'high':'max', 'low':'min', 'close':'last', 'volume':'sum'}).dropna()
        c5['ema20'] = c5['close'].ewm(span=20, adjust=False).mean()
        c5['ema50'] = c5['close'].ewm(span=50, adjust=False).mean()
        c5['tr'] = np.maximum(c5['high']-c5['low'], np.maximum(abs(c5['high']-c5['close'].shift(1)), abs(c5['low']-c5['close'].shift(1))))
        c5['atr'] = c5['tr'].rolling(window=14, min_periods=1).mean()
        
        delta = c5['close'].diff()
        gain = (delta.where(delta>0, 0)).rolling(window=14, min_periods=1).mean()
        loss = (-delta.where(delta<0, 0)).rolling(window=14, min_periods=1).mean()
        rs = gain / loss
        c5['rsi'] = 100 - (100 / (1 + rs))
        
        self.state.candles_5m = c5.reset_index()
        if not c5.empty:
            last = c5.iloc[-1]
            self.state.indicators['rsi'] = last['rsi'] if not pd.isna(last['rsi']) else None
            logger.info(f"5m Candle: C={last['close']}, ATR={last['atr']}, RSI={self.state.indicators['rsi']}")

        c15 = df.resample('15min').agg({'open':'first', 'high':'max', 'low':'min', 'close':'last', 'volume':'sum'}).dropna()
        c15['ema20'] = c15['close'].ewm(span=20, adjust=False).mean()
        c15['ema50'] = c15['close'].ewm(span=50, adjust=False).mean()
        self.state.candles_15m = c15.reset_index()

    def calculate_obi(self):
        if not self.state.orderbook['bids']: return
        
        # Sort and take top 10
        sorted_bids = sorted(self.state.orderbook['bids'].items(), key=lambda x: x[0], reverse=True)[:10]
        sorted_asks = sorted(self.state.orderbook['asks'].items(), key=lambda x: x[0])[:10]
        
        if not sorted_bids or not sorted_asks: return

        bid_vol = sum(size for price, size in sorted_bids)
        ask_vol = sum(size for price, size in sorted_asks)
        total = bid_vol + ask_vol
        raw_obi = (bid_vol - ask_vol) / total if total > 0 else 0
        
        current = self.state.indicators.get('obi', 0.0) or 0.0
        self.state.indicators['obi'] = (0.3 * raw_obi) + (0.7 * current)
        
        # Spread
        bb = sorted_bids[0][0]
        ba = sorted_asks[0][0]
        mid = (ba + bb) / 2
        self.state.indicators['spread'] = (ba - bb) / mid * 10000
        
        # Depth
        min_d = min(sum(p*s for p,s in sorted_bids), sum(p*s for p,s in sorted_asks))
        self.state.indicators['depth'] = min_d
        cur_d = self.state.indicators.get('smoothed_depth', 0.0)
        self.state.indicators['smoothed_depth'] = (0.1 * min_d) + (0.9 * cur_d)

    def calculate_cvd(self):
        now = time.time()
        trades = list(self.state.trades)
        
        bv1 = sum(t['size'] for t in trades if t['side']=='Buy' and t['time']>now-60)
        sv1 = sum(t['size'] for t in trades if t['side']=='Sell' and t['time']>now-60)
        tot1 = bv1 + sv1
        r1 = (bv1 - sv1)/tot1 if tot1>0 else 0
        
        bv5 = sum(t['size'] for t in trades if t['side']=='Buy' and t['time']>now-300)
        sv5 = sum(t['size'] for t in trades if t['side']=='Sell' and t['time']>now-300)
        tot5 = bv5 + sv5
        r5 = (bv5 - sv5)/tot5 if tot5>0 else 0
        
        c1 = self.state.indicators.get('cvd_1m', 0.0) or 0.0
        c5 = self.state.indicators.get('cvd_5m', 0.0) or 0.0
        self.state.indicators['cvd_1m'] = (0.3 * r1) + (0.7 * c1)
        self.state.indicators['cvd_5m'] = (0.3 * r5) + (0.7 * c5)

    def update_oi_change(self): pass

    def determine_regime(self):
        if len(self.state.candles_5m) < 2: return
        c5 = self.state.candles_5m.iloc[-1]
        c15 = self.state.candles_15m.iloc[-1] if not self.state.candles_15m.empty else c5
        
        s5 = c5['ema20'] - self.state.candles_5m.iloc[-2]['ema20']
        self.state.trends['5m'] = "BULL" if c5['ema20']>c5['ema50'] and s5>0 else "BEAR" if c5['ema20']<c5['ema50'] and s5<0 else "NEUTRAL"
        
        atr = c5['atr']
        self.state.indicators['atr'] = atr
        spread = self.state.indicators.get('spread', 0.0)
        
        is_chaotic = (spread > 5)
        if is_chaotic: self.state.regime = "CHAOTIC"
        elif self.state.trends['5m'] == "BULL": self.state.regime = "TRENDING_BULL"
        elif self.state.trends['5m'] == "BEAR": self.state.regime = "TRENDING_BEAR"
        else: self.state.regime = "RANGING"

    def check_gates(self):
        now = time.time()
        spread = self.state.indicators.get('spread')
        depth = self.state.indicators.get('smoothed_depth')
        if spread is None or depth is None: return
        
        if self.state.gate_state_depth == "PASS":
            if depth < 40000 and self.should_flip(now): self.state.gate_state_depth = "FAIL"
        else:
            if depth > 50000 and self.should_flip(now): self.state.gate_state_depth = "PASS"
            
        if self.state.gate_state_spread == "PASS":
            if spread > 2.0 and self.should_flip(now): self.state.gate_state_spread = "FAIL"
        else:
            if spread < 1.5 and self.should_flip(now): self.state.gate_state_spread = "PASS"
            
        self.state.gates_passed = (self.state.gate_state_depth == "PASS") and (self.state.gate_state_spread == "PASS")

    def should_flip(self, now):
        if now - self.state.last_gate_change > 3:
            self.state.last_gate_change = now
            return True
        return False

    def build_checklist(self):
        is_trending = "TRENDING" in self.state.regime
        s5 = self.state.trends['5m']
        cvd = self.state.indicators.get('cvd_5m', 0.0) or 0.0
        obi = self.state.indicators.get('obi', 0.0) or 0.0
        ema20 = self.state.indicators.get('ema20_1m', 0.0)
        
        cvd_pass = (cvd > 0.15) if "BULL" in self.state.regime else (cvd < -0.15)
        obi_pass = (obi > 0.12) if "BULL" in self.state.regime else (obi < -0.12)
        
        ema_pass = False
        dist_str = "-"
        if ema20 and self.state.price > 0:
            dist = abs(self.state.price - ema20) / ema20 * 100
            dist_str = f"{dist:.3f}%"
            ema_pass = dist < 0.3
            
        self.state.checklist = {
            "regime": {"pass": is_trending, "value": self.state.regime},
            "structure": {"pass": True, "value": f"5M {s5}"},
            "cvd": {"pass": cvd_pass, "value": f"{cvd:.2f}"},
            "obi": {"pass": obi_pass, "value": f"{obi:.2f}"},
            "ema_dist": {"pass": ema_pass, "value": dist_str},
            "gates": {"pass": self.state.gates_passed, "value": "PASS" if self.state.gates_passed else "FAIL"}
        }

    async def processing_loop(self):
        while self.running:
            try:
                await asyncio.sleep(1)
                
                if not self.state.is_warmed_up:
                    c1 = len(self.state.candles_1m)
                    self.state.warmup_progress = min(100, int(c1/50 * 100))
                    if c1 >= 50: 
                        self.state.is_warmed_up = True
                        logger.info("Warmup Complete")
                
                if time.time() - self.state.last_update > 10:
                    logger.warning("Data stale")
                    continue
                    
                self.calculate_cvd()
                self.determine_regime()
                self.check_gates()
                self.build_checklist()
                
                if self.state.is_warmed_up:
                    await self.manage_signals()
            except Exception as e:
                logger.error(f"Loop error: {e}")
                await asyncio.sleep(1)

    async def manage_signals(self):
        now = time.time()
        if self.signal_state.status == "ACTIVE":
            if now > self.signal_state.active_until:
                self.signal_state.status = "IDLE"
                self.signal_state.cooldown_until = now + 600
                self.signal_state.current_signal = None
            return

        if now < self.signal_state.cooldown_until: return

        checklist = self.state.checklist
        core_pass = (
            checklist['regime']['pass'] and 
            checklist['cvd']['pass'] and 
            checklist['obi']['pass'] and 
            checklist['ema_dist']['pass']
        )
        
        if self.signal_state.status == "IDLE":
            if core_pass and self.state.gates_passed:
                self.signal_state.status = "FORMING"
                self.signal_state.forming_since = now
                logger.info("Signal FORMING...")
        
        elif self.signal_state.status == "FORMING":
            if not core_pass:
                self.signal_state.status = "IDLE"
                return
            
            if now - self.signal_state.forming_since >= 30:
                await self.activate_signal()

    async def activate_signal(self):
        self.signal_state.status = "ACTIVE"
        now = time.time()
        self.signal_state.active_until = now + 300
        
        signal = {
            "id": str(int(now)),
            "direction": "LONG" if "BULL" in self.state.regime else "SHORT",
            "entry_min": self.state.price,
            "entry_max": self.state.price,
            "stop_loss": 0, "tp1": 0, "tp2": 0,
            "sl_pct": 0, "tp1_pct": 0, "tp2_pct": 0, "rr_ratio": 0,
            "confidence": 80,
            "reasons": ["Core Pass", "Gates Pass"],
            "timestamp": now
        }
        self.signal_state.current_signal = signal
        logger.info(f"Signal ACTIVATED: {signal}")
        if self.telegram: await self.telegram.send_signal(signal)
