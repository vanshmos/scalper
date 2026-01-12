# Crypto Scalping Signal Engine V2.1

A sophisticated real-time crypto scalping signal engine for BTC, ETH, and SOL perpetual futures. Uses OKX WebSocket data to generate high-quality trading signals with Telegram alerts.

**Current Version:** V2.1 Rebalanced (January 2026)  
**Signal Threshold:** 75 (forming: 70)  
**Target Win Rate:** 65-70%  
**Expected Frequency:** 3-8 signals/day across 3 symbols

## Features

- **Real-time Data:** OKX WebSocket feeds for candles (1m, 5m, 15m), trades, and order books
- **Multi-Symbol:** Simultaneous monitoring of BTC, ETH, and SOL perpetual swaps
- **Advanced Indicators:** EMA, RSI, ATR, CVD, OBI, Bollinger Bands, VWAP, and more
- **Institutional-Grade Logic:** Velocity signals, liquidity sweep detection, regime-aware scoring
- **Adaptive Targets:** Dynamic TP/SL based on market volatility and trend strength ($100K capital, 10x leverage)
- **State Persistence:** Survives restarts with saved candle and CVD/OBI history
- **Trade Accountability:** Full trade tracking with P&L, ROI, and performance analytics (SQLite)
- **Web Dashboard:** Real-time multi-symbol interface with live indicators and signal status
- **Telegram Alerts:** Instant notifications for high-quality signals

## Features

### Phase 1: Data Connection
- ✅ OKX WebSocket connection (wss://ws.okx.com:8443/ws/v5/public)
- ✅ Real-time orderbook (50 levels), trades, and ticker data
- ✅ 1-minute candle building from live trade stream
- ✅ Automatic resampling to 5m and 15m timeframes
- ✅ Historical backfill (100 candles from OKX REST API on startup)
- ✅ File persistence (saves every 60 seconds, loads on restart)
- ✅ Auto-reconnect on disconnect (5-second retry)

### Phase 2: Indicators
**Trend Indicators:**
- EMA20 and EMA50 on 1m, 5m, 15m candles
- Approximation mode when warming up (shows ⚠️ warning)

**Volatility:**
- ATR 14-period on 5m candles

**Momentum:**
- RSI 14-period on 5m candles

**Orderbook Metrics:**
- OBI (Order Book Imbalance): (bid volume - ask volume) / total volume for top 10 levels
- Spread: (best ask - best bid) / mid price × 10000 (in bps)
- Depth: minimum of bid/ask depth for top 10 levels

**Volume Flow:**
- CVD 1m: (buy volume - sell volume) / total volume for last 60 seconds
- CVD 5m: same for last 300 seconds
- Exponential smoothing (alpha 0.1) on OBI, CVD, depth

### Phase 3: Regime Detection & Gates
**Market Regimes:**
- TRENDING_BULL: 5m & 15m EMAs bullish with positive slope
- TRENDING_BEAR: 5m & 15m EMAs bearish with negative slope
- RANGING: Low volatility, no clear trend
- CHAOTIC: ATR > 2× baseline or spread > 5 bps

**Gates (with hysteresis):**
- Spread gate: < 2 bps
- Depth gate: > $60k to pass, < $40k to fail (prevents flickering)

### Phase 4: Signal Detection
**SHORT Signal Checklist:**
1. Regime: TRENDING_BEAR
2. Structure: 5m BEAR and 15m BEAR
3. CVD 5m < -0.15
4. OBI < -0.12
5. Price within 0.5% of EMA20 on 1m

**LONG Signal Checklist:**
1. Regime: TRENDING_BULL
2. Structure: 5m BULL and 15m BULL
3. CVD 5m > 0.15
4. OBI > 0.12
5. Price within 0.5% of EMA20 on 1m

**Confidence Score (0-100):**
- Structure aligned: 30 points
- CVD strength: 25 points (scaled)
- OBI strength: 20 points (scaled)
- Pullback quality: 20 points
- Funding context: 5 points
- RSI penalty: -15 if extreme
- Minimum score: 70

### Phase 5: Signal State Machine
**States:** IDLE → FORMING (20s) → ACTIVE (5min) → EXPIRED → IDLE (10min cooldown)

**Locked Levels (when ACTIVE):**
- Entry: Current price
- Stop Loss: 1.5 × ATR
- TP1: 2 × ATR
- TP2: 3.5 × ATR

### Phase 6: Alerts
- Browser audio alert (with mute button)
- Telegram alerts (optional, configure via .env)

## Configuration

Add to `/app/backend/.env`:
```bash
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

Then restart: `sudo supervisorctl restart backend`

## Logs

```bash
tail -f /var/log/supervisor/backend.*.log
```

## Dashboard

Access at http://localhost:3000
- Real-time price & indicators
- Signal checklists with confidence scores
- Active signal card (when FORMING/ACTIVE)
- Mute button for audio alerts

## Technical Stack

- Backend: FastAPI + Python
- Frontend: React
- WebSocket: OKX public stream
- Database: MongoDB (for candle persistence)
- Real-time updates: 500ms intervals

**Signals only - no execution**
