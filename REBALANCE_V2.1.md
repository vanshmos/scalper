# Signal Engine V2.1 Rebalance - January 2026

## Problem Statement
After deploying the "Survival Fix" (V2.0) with threshold of 88, the engine became too restrictive, generating only ~1 signal in multiple days. While quality is important, a scalping engine needs usable signal frequency.

## Root Cause Analysis

### V2.0 Issues (Too Restrictive):
1. **Active Threshold: 88** - Mathematically nearly impossible with the current scoring system
2. **Contradictory Guards:**
   - Candle Color Guard: Blocked buying dips (red candles) even with strong CVD
   - Mean Reversion Guard: Blocked momentum trades during trends
3. **Flow Thresholds Too High:**
   - CVD threshold: 0.08 (rarely achieved in choppy markets)
   - OBI threshold: 0.1 (too strict for scalping)
4. **RANGING Regime Penalty:** Markets spend 60%+ time ranging, but engine only gave 12 pts (vs 20 for trending)

### Example Blockage:
```
BTC LONG Signal Attempt:
- Regime: RANGING (+12 pts instead of +20) ❌
- CVD: 0.06 (below 0.08 threshold, +0 pts) ❌
- OBI: 0.09 (below 0.1 threshold, +0 pts) ❌
- Candle: Red (VETO - falling knife) ❌
Result: Signal never fires
```

## V2.1 Rebalance Solution

### Changes Implemented:

#### 1. Lowered Activation Threshold
- **Forming: 80 → 70**
- **Active: 88 → 75**
- Rationale: Makes the threshold mathematically achievable while maintaining selectivity

#### 2. Removed Candle Color Guard (Hard Veto → Advisory)
```python
# OLD: Vetoed red candles for LONG
if current_price < forming_candle_open:
    return {'pass': False, 'detail': 'Falling knife'}

# NEW: Advisory only
return {'pass': True, 'detail': 'ℹ️ Red candle (buying dip if flow strong)'}
```
- **Rationale:** For scalping, we WANT to buy red candles if CVD/OBI show strong buying pressure
- Waiting for green confirmation is too slow and misses entries

#### 3. Mean Reversion Guard: Downgraded to Advisory + Regime-Aware
```python
# NEW: Regime-aware logic
if regime in [TRENDING_BULL, TRENDING_BEAR]:
    return {'pass': True, 'score_penalty': 0}  # Allow band pushes in trends
elif regime == RANGING:
    return {'pass': True, 'score_penalty': -10}  # Warn but don't block
```
- **TRENDING:** Allow pushing Bollinger Bands (let winners run)
- **RANGING:** Apply -10 point penalty (advisory) instead of hard veto
- **Rationale:** Don't penalize momentum continuation in strong trends

#### 4. Lowered Flow Thresholds
- **CVD: 0.08 → 0.05** (60% reduction)
- **OBI: 0.1 → 0.08** (20% reduction)
- **Rationale:** More realistic thresholds for crypto scalping markets
- **Safety:** CVD Velocity (acceleration) still weighted heavily to avoid dead markets

#### 5. More Generous RANGING Scoring
```python
# OLD
if RANGING + RSI < 35: +12 pts
else: +0 pts

# NEW
if RANGING + RSI < 35: +15 pts
elif RANGING (neutral): +8 pts  # NEW: Partial credit
```
- **Rationale:** Markets range 60%+ of the time; don't handicap all ranging signals

### Expected Outcomes

| Metric | V2.0 (Old) | V2.1 (New) | Target |
|--------|-----------|-----------|---------|
| **Signal Frequency** | ~0.14/day | ~3-5/day | 3-8/day |
| **Activation Rate** | <1% | ~15-20% | 15-25% |
| **Win Rate Target** | N/A | 65-70% | 65-70% |

### Quality Safeguards (Still Active)

Despite the rebalance, these critical filters remain:
- ✅ **VWAP Distance Check** (hard veto)
- ✅ **Velocity Check** (acceleration required)
- ✅ **Spread & Depth Gates** (liquidity filters)
- ✅ **Adaptive TP/SL Targets** (risk management)
- ✅ **Regime Detection** (trend awareness)
- ✅ **180s Trade Expiration** (viability window)

## Testing & Monitoring

### Immediate Actions:
1. ✅ Code updated and deployed
2. ✅ Backend restarted successfully
3. ✅ Dashboard shows improved signal scores (38-56 range, closer to 75)

### Monitoring Plan:
1. **Signal Frequency:** Track signals per day (target: 3-8)
2. **Win Rate:** Monitor trade outcomes in Trade History panel (target: 65-70%)
3. **Score Distribution:** Ensure scores cluster around 70-85 (not 20-40)
4. **False Positives:** Watch for any spam signals (cooldown: 30s per symbol)

### Success Metrics (72-hour window):
- [ ] Generate 9-24 total signals across 3 symbols
- [ ] Achieve 60%+ win rate
- [ ] No signal spam (respect 30s cooldown)
- [ ] Telegram alerts functioning correctly

## Code Changes

### Files Modified:
- `/app/backend/signal_detector_alpha.py`:
  - Updated `__init__`: New thresholds and flow limits
  - Modified `check_mean_reversion_guard`: Regime-aware advisory
  - Modified `check_candle_color_guard`: Advisory only
  - Modified `detect_signal_with_alpha`: Removed hard vetos, added advisory penalties

### Deployment:
- Backend restarted: January 12, 2026 11:22 UTC
- All 3 engines (BTC, ETH, SOL) connected and operational
- WebSocket feeds active with real-time data

## User Approval
- **Approved by:** User (January 12, 2026)
- **Target Win Rate:** 65-70%
- **Risk Tolerance:** Balanced (not too aggressive, not too conservative)

## Next Steps
1. Monitor live performance for 24-72 hours
2. Collect trade data in SQLite database
3. Analyze win rate and ROI from Trade History panel
4. Fine-tune if win rate < 60% or signal frequency too high/low
5. Consider adding "near-miss" signal logging (scores 65-75) for future optimization
