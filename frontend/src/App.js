import { useEffect, useState, useRef } from "react";
import "@/App.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const WS_URL = BACKEND_URL.replace('https://', 'wss://').replace('http://', 'ws://');

function App() {
  const [status, setStatus] = useState({btc: null, eth: null, sol: null});
  const [wsConnected, setWsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [audioMuted, setAudioMuted] = useState(false);
  const [activeSymbol, setActiveSymbol] = useState('btc');
  const audioRef = useRef(null);
  const lastSignalStates = useRef({btc: 'IDLE', eth: 'IDLE', sol: 'IDLE'});

  useEffect(() => {
    let ws = null;
    let reconnectTimer = null;

    const connect = () => {
      try {
        ws = new WebSocket(`${WS_URL}/api/ws`);

        ws.onopen = () => {
          console.log('WebSocket connected');
          setWsConnected(true);
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            setStatus(data);
            setLastUpdate(new Date().toLocaleTimeString());
            
            // Check for signal state transition to ACTIVE for any symbol
            for (const symbol of ['btc', 'eth', 'sol']) {
              const currentState = data[symbol]?.signal_status?.state;
              if (currentState === 'ACTIVE' && lastSignalStates.current[symbol] !== 'ACTIVE') {
                // Signal just became ACTIVE - play alert sound
                if (!audioMuted && audioRef.current) {
                  audioRef.current.play().catch(err => console.log('Audio play failed:', err));
                }
              }
              lastSignalStates.current[symbol] = currentState;
            }
            
          } catch (e) {
            console.error('Error parsing WebSocket message:', e);
          }
        };

        ws.onerror = (error) => {
          console.error('WebSocket error:', error);
          setWsConnected(false);
        };

        ws.onclose = () => {
          console.log('WebSocket disconnected');
          setWsConnected(false);
          // Reconnect after 5 seconds
          reconnectTimer = setTimeout(connect, 5000);
        };
      } catch (e) {
        console.error('Error creating WebSocket:', e);
        reconnectTimer = setTimeout(connect, 5000);
      }
    };

    connect();

    return () => {
      if (ws) {
        ws.close();
      }
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
    };
  }, []);

  const formatPrice = (price) => {
    if (price === null || price === undefined) return '—';
    return `$${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const formatNumber = (num, decimals = 2) => {
    if (num === null || num === undefined) return '—';
    return num.toFixed(decimals);
  };

  const getIndicatorColor = (value, bullishThreshold, bearishThreshold) => {
    if (value === null || value === undefined) return '';
    if (value > bullishThreshold) return 'text-green';
    if (value < bearishThreshold) return 'text-red';
    return '';
  };

  // Get data for active symbol
  const symbolData = status[activeSymbol] || {};
  const indicators = symbolData.indicators || {};
  const regime = symbolData.regime || 'RANGING';
  const gates = symbolData.gates || {};
  const signals = symbolData.signals || {};
  const approximating = symbolData.approximating || {};
  const signalStatus = symbolData.signal_status || {};

  const getRegimeColor = (regime) => {
    switch(regime) {
      case 'TRENDING_BULL': return 'regime-bull';
      case 'TRENDING_BEAR': return 'regime-bear';
      case 'CHAOTIC': return 'regime-chaotic';
      default: return 'regime-ranging';
    }
  };

  const getRegimeLabel = (regime) => {
    return regime.replace('_', ' ');
  };

  return (
    <div className="app-container" data-testid="crypto-dashboard">
      {/* Hidden audio element for alert sound */}
      <audio ref={audioRef} src="data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2/LDciUFLIHO8tiJNwgZaLvt559NEAxQp+PwtmMcBjiR1/LMeSwFJHfH8N2QQAoUXrTp66hVFApGn+DyvmwhBCuC0PLNfC0GI3vJ8dybRgsXZLnp6aVMEgxMouHyvWklBCl/zvLLfCsGJX3N8dybRgsWYbfm66hVFApFneDxvmwjBCl+zvLLfCsGJX3N8dybRgsWYbfm66hVFApFneDxvmwjBCl+zvLLfCsGJX3N8dybRgsWYbfm66hVFApFneDxvmwjBCl+zvLLfCsGJX3N8dybRgsWYbfm66hVFApFneDxvmwjBCl+zvLLfCsGJX3N8dybRgsWYbfm66hVFApFneDxvmwjBCl+zvLLfCsGJX3N8dybRgsWYbfm66hVFApFneDxvmwjBCl+zvLLfCsGJX3N8dyb" />
      
      <div className="header">
        <h1 className="title" data-testid="dashboard-title">SCALPING ENGINE</h1>
        <div className="header-status">
          <div className={`status-indicator ${wsConnected ? 'connected' : 'disconnected'}`} data-testid="connection-indicator">
            <div className="status-dot"></div>
            <span>{wsConnected ? 'OKX CONNECTED (3 symbols)' : 'DISCONNECTED'}</span>
          </div>
          <button 
            className={`mute-button ${audioMuted ? 'muted' : ''}`}
            onClick={() => setAudioMuted(!audioMuted)}
            data-testid="mute-button"
            title={audioMuted ? 'Unmute alerts' : 'Mute alerts'}
          >
            {audioMuted ? '🔇' : '🔊'}
          </button>
          {lastUpdate && (
            <div className="last-update" data-testid="last-update">Updated: {lastUpdate}</div>
          )}
        </div>
      </div>

      {/* Symbol Tabs */}
      <div className="symbol-tabs">
        <button 
          className={`symbol-tab ${activeSymbol === 'btc' ? 'active' : ''}`}
          onClick={() => setActiveSymbol('btc')}
          data-testid="tab-btc"
        >
          BTC
        </button>
        <button 
          className={`symbol-tab ${activeSymbol === 'eth' ? 'active' : ''}`}
          onClick={() => setActiveSymbol('eth')}
          data-testid="tab-eth"
        >
          ETH
        </button>
        <button 
          className={`symbol-tab ${activeSymbol === 'sol' ? 'active' : ''}`}
          onClick={() => setActiveSymbol('sol')}
          data-testid="tab-sol"
        >
          SOL
        </button>
      </div>

      {/* Active Signal Card - Only show when FORMING or ACTIVE */}
      {(signalStatus.state === 'FORMING' || signalStatus.state === 'ACTIVE') && (
        <div className="active-signal-card" data-testid="active-signal-card">
          <div className="signal-card-header">
            <div className={`signal-direction ${signalStatus.direction?.toLowerCase()}`}>
              {signalStatus.direction === 'SHORT' ? '🔴' : '🟢'} {signalStatus.direction} {activeSymbol.toUpperCase()}
            </div>
            <div className={`signal-state ${signalStatus.state.toLowerCase()}`}>
              {signalStatus.state}
            </div>
          </div>
          
          {signalStatus.state === 'FORMING' && (
            <div className="signal-card-content">
              <div className="countdown">
                <div className="countdown-label">Forming Timer</div>
                <div className="countdown-value" data-testid="forming-countdown">
                  {Math.ceil(signalStatus.forming_remaining || 0)}s
                </div>
                <div className="countdown-bar">
                  <div 
                    className="countdown-progress"
                    style={{width: `${((signalStatus.forming_elapsed || 0) / 20) * 100}%`}}
                  ></div>
                </div>
              </div>
            </div>
          )}
          
          {signalStatus.state === 'ACTIVE' && (
            <div className="signal-card-content">
              <div className="signal-levels">
                <div className="level-row">
                  <span>Entry:</span>
                  <span className="level-value" data-testid="signal-entry">${signalStatus.entry?.toFixed(2)}</span>
                </div>
                <div className="level-row">
                  <span>Stop Loss:</span>
                  <span className="level-value text-red" data-testid="signal-sl">${signalStatus.stop_loss?.toFixed(2)}</span>
                </div>
                <div className="level-row">
                  <span>TP1:</span>
                  <span className="level-value text-green" data-testid="signal-tp1">${signalStatus.tp1?.toFixed(2)}</span>
                </div>
                <div className="level-row">
                  <span>TP2:</span>
                  <span className="level-value text-green" data-testid="signal-tp2">${signalStatus.tp2?.toFixed(2)}</span>
                </div>
                <div className="level-row">
                  <span>Confidence:</span>
                  <span className="level-value" data-testid="signal-confidence-active">{signalStatus.confidence}/100</span>
                </div>
              </div>
              
              <div className="countdown">
                <div className="countdown-label">Time Remaining</div>
                <div className="countdown-value" data-testid="active-countdown">
                  {Math.floor((signalStatus.active_remaining || 0) / 60)}:{String(Math.floor((signalStatus.active_remaining || 0) % 60)).padStart(2, '0')}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="content">
        {/* Price Display */}
        <div className="price-section">
          <div className="section-row">
            <div className="price-container">
              <div className="section-label">{activeSymbol.toUpperCase()} PRICE</div>
              <div className="price-display" data-testid="current-price">
                {symbolData.current_price ? formatPrice(symbolData.current_price) : '—'}
              </div>
            </div>
            <div className="regime-container">
              <div className="section-label">MARKET REGIME</div>
              <div className={`regime-badge ${getRegimeColor(regime)}`} data-testid="regime-badge">
                {getRegimeLabel(regime)}
              </div>
            </div>
          </div>
        </div>

        {/* Connection Status */}
        <div className="info-card">
          <div className="card-header">CONNECTION</div>
          <div className="card-content">
            <div className="info-row">
              <span className="info-label">Symbol:</span>
              <span className="info-value text-green" data-testid="symbol-name">
                {activeSymbol.toUpperCase()}-USDT-SWAP
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">Status:</span>
              <span className={`info-value ${symbolData.connected ? 'text-green' : 'text-red'}`} data-testid="symbol-status">
                {symbolData.connected ? 'CONNECTED' : 'DISCONNECTED'}
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">Last Update:</span>
              <span className="info-value" data-testid="last-symbol-update">
                {symbolData.last_update ? new Date(symbolData.last_update).toLocaleTimeString() : '—'}
              </span>
            </div>
          </div>
        </div>

        {/* Candle Counts */}
        <div className="info-card">
          <div className="card-header">CANDLE DATA</div>
          <div className="card-content">
            <div className="info-row">
              <span className="info-label">1m Candles:</span>
              <span className="info-value text-green" data-testid="candles-1m">
                {symbolData.candle_counts?.['1m'] ?? '—'}
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">5m Candles:</span>
              <span className="info-value text-green" data-testid="candles-5m">
                {symbolData.candle_counts?.['5m'] ?? '—'}
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">15m Candles:</span>
              <span className="info-value text-green" data-testid="candles-15m">
                {symbolData.candle_counts?.['15m'] ?? '—'}
              </span>
            </div>
          </div>
        </div>

        {/* Gates Status */}
        <div className="info-card">
          <div className="card-header">PHASE 3: GATES</div>
          <div className="card-content">
            <div className="info-row">
              <span className="info-label">Spread Gate:</span>
              <span className={`info-value ${gates.spread?.pass ? 'text-green' : 'text-red'}`} data-testid="gate-spread">
                {gates.spread?.pass ? 'PASS' : 'FAIL'}
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">Spread Value:</span>
              <span className="info-value">{formatNumber(gates.spread?.value, 2)} bps</span>
            </div>
            <div className="info-row">
              <span className="info-label">Depth Gate:</span>
              <span className={`info-value ${gates.depth?.pass ? 'text-green' : 'text-red'}`} data-testid="gate-depth">
                {gates.depth?.pass ? 'PASS' : 'FAIL'}
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">Depth Value:</span>
              <span className="info-value">${formatNumber(gates.depth?.value, 0)}</span>
            </div>
            <div className="info-row">
              <span className="info-label">All Gates:</span>
              <span className={`info-value ${gates.all_pass ? 'text-green' : 'text-red'}`} data-testid="gate-all">
                {gates.all_pass ? 'PASS' : 'FAIL'}
                {gates.data_stale && <span className="stale-warning" title="Data may be stale"> ⚠️</span>}
              </span>
            </div>
          </div>
        </div>

        {/* Phase Status */}
        <div className="info-card">
          <div className="card-header">PHASE 2: INDICATORS</div>
          <div className="card-content">
            <div className="indicator-section">
              <div className="indicator-title">
                EMA (1m)
                {approximating['1m'] && <span className="approx-warning" title="Approximating - warming up"> ⚠️</span>}
              </div>
              <div className="indicator-row">
                <span>EMA20:</span>
                <span data-testid="ema20-1m">{formatPrice(indicators.ema?.['1m']?.ema20)}</span>
              </div>
              <div className="indicator-row">
                <span>EMA50:</span>
                <span data-testid="ema50-1m">{formatPrice(indicators.ema?.['1m']?.ema50)}</span>
              </div>
            </div>
            
            <div className="indicator-section">
              <div className="indicator-title">
                EMA (5m)
                {approximating['5m'] && <span className="approx-warning" title="Approximating - warming up"> ⚠️</span>}
              </div>
              <div className="indicator-row">
                <span>EMA20:</span>
                <span data-testid="ema20-5m">{formatPrice(indicators.ema?.['5m']?.ema20)}</span>
              </div>
              <div className="indicator-row">
                <span>EMA50:</span>
                <span data-testid="ema50-5m">{formatPrice(indicators.ema?.['5m']?.ema50)}</span>
              </div>
            </div>
            
            <div className="indicator-section">
              <div className="indicator-title">
                EMA (15m)
                {approximating['15m'] && <span className="approx-warning" title="Approximating - warming up"> ⚠️</span>}
              </div>
              <div className="indicator-row">
                <span>EMA20:</span>
                <span data-testid="ema20-15m">{formatPrice(indicators.ema?.['15m']?.ema20)}</span>
              </div>
              <div className="indicator-row">
                <span>EMA50:</span>
                <span data-testid="ema50-15m">{formatPrice(indicators.ema?.['15m']?.ema50)}</span>
              </div>
            </div>
            
            <div className="indicator-section">
              <div className="indicator-title">5m Indicators</div>
              <div className="indicator-row">
                <span>ATR 14:</span>
                <span data-testid="atr-5m">{formatNumber(indicators.atr_5m)}</span>
              </div>
              <div className="indicator-row">
                <span>RSI 14:</span>
                <span data-testid="rsi-5m" className={getIndicatorColor(indicators.rsi_5m, 75, 25)}>
                  {formatNumber(indicators.rsi_5m)}
                </span>
              </div>
            </div>
            
            <div className="indicator-section">
              <div className="indicator-title">Orderbook</div>
              <div className="indicator-row">
                <span>OBI:</span>
                <span data-testid="obi" className={getIndicatorColor(indicators.obi, 0.12, -0.12)}>
                  {formatNumber(indicators.obi, 3)}
                </span>
              </div>
              <div className="indicator-row">
                <span>Spread (bps):</span>
                <span data-testid="spread">{formatNumber(indicators.spread, 2)}</span>
              </div>
              <div className="indicator-row">
                <span>Depth:</span>
                <span data-testid="depth">${formatNumber(indicators.depth, 0)}</span>
              </div>
            </div>
            
            <div className="indicator-section">
              <div className="indicator-title">CVD</div>
              <div className="indicator-row">
                <span>CVD 1m:</span>
                <span data-testid="cvd-1m" className={getIndicatorColor(indicators.cvd?.['1m'], 0.15, -0.15)}>
                  {formatNumber(indicators.cvd?.['1m'], 3)}
                </span>
              </div>
              <div className="indicator-row">
                <span>CVD 5m:</span>
                <span data-testid="cvd-5m" className={getIndicatorColor(indicators.cvd?.['5m'], 0.15, -0.15)}>
                  {formatNumber(indicators.cvd?.['5m'], 3)}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Signal Checklist - SHORT */}
        <div className="info-card signal-card">
          <div className="card-header">SHORT SIGNAL (V1.5)</div>
          <div className="card-content">
            <div className="confidence-row">
              <span>Score:</span>
              <span className={`confidence-value quality-${signals.short?.quality?.toLowerCase()}`} data-testid="short-score">
                {signals.short?.score || 0}/100 ({signals.short?.quality || 'LOW'})
              </span>
            </div>
            
            <div className="scoring-breakdown">
              <div className="breakdown-title">Scoring Breakdown:</div>
              {signals.short?.breakdown && Object.entries(signals.short.breakdown).map(([key, value]) => (
                <div key={key} className="breakdown-item">
                  <span className="breakdown-label">{key}:</span>
                  <span className="breakdown-detail">{value.detail}</span>
                  <span className="breakdown-points">+{value.points}</span>
                </div>
              ))}
              <div className="breakdown-total">
                <span>Total:</span>
                <span className="total-score">{signals.short?.score || 0}</span>
              </div>
            </div>
            
            <div className="hard-gates-section">
              <div className="gates-title">Hard Gates:</div>
              {signals.short?.hard_gates && (
                <>
                  <div className={`gate-item ${signals.short.hard_gates.regime_filter?.pass ? 'pass' : 'fail'}`}>
                    <span className="gate-icon">{signals.short.hard_gates.regime_filter?.pass ? '✓' : '✗'}</span>
                    <span>Regime Filter: {signals.short.hard_gates.regime_filter?.detail || 'N/A'}</span>
                  </div>
                  <div className={`gate-item ${signals.short.hard_gates.rsi_filter?.pass ? 'pass' : 'fail'}`}>
                    <span className="gate-icon">{signals.short.hard_gates.rsi_filter?.pass ? '✓' : '✗'}</span>
                    <span>RSI (30-70): {signals.short.hard_gates.rsi_filter?.detail || 'N/A'}</span>
                  </div>
                  <div className={`gate-item ${signals.short.hard_gates.ema_proximity?.pass ? 'pass' : 'fail'}`}>
                    <span className="gate-icon">{signals.short.hard_gates.ema_proximity?.pass ? '✓' : '✗'}</span>
                    <span>EMA Proximity (&lt;1%): {signals.short.hard_gates.ema_proximity?.detail || 'N/A'}</span>
                  </div>
                  <div className={`gate-item ${signals.short.hard_gates.spread?.pass ? 'pass' : 'fail'}`}>
                    <span className="gate-icon">{signals.short.hard_gates.spread?.pass ? '✓' : '✗'}</span>
                    <span>Spread (&lt;5 bps): {signals.short.hard_gates.spread?.detail || 'N/A'}</span>
                  </div>
                  <div className={`gate-item ${signals.short.hard_gates.directional_alignment?.pass ? 'pass' : 'fail'}`}>
                    <span className="gate-icon">{signals.short.hard_gates.directional_alignment?.pass ? '✓' : '✗'}</span>
                    <span>CVD/OBI Alignment: {signals.short.hard_gates.directional_alignment?.detail || 'N/A'}</span>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Signal Checklist - LONG */}
        <div className="info-card signal-card">
          <div className="card-header">LONG SIGNAL (V1.5)</div>
          <div className="card-content">
            <div className="confidence-row">
              <span>Score:</span>
              <span className={`confidence-value quality-${signals.long?.quality?.toLowerCase()}`} data-testid="long-score">
                {signals.long?.score || 0}/100 ({signals.long?.quality || 'LOW'})
              </span>
            </div>
            
            <div className="scoring-breakdown">
              <div className="breakdown-title">Scoring Breakdown:</div>
              {signals.long?.breakdown && Object.entries(signals.long.breakdown).map(([key, value]) => (
                <div key={key} className="breakdown-item">
                  <span className="breakdown-label">{key}:</span>
                  <span className="breakdown-detail">{value.detail}</span>
                  <span className="breakdown-points">+{value.points}</span>
                </div>
              ))}
              <div className="breakdown-total">
                <span>Total:</span>
                <span className="total-score">{signals.long?.score || 0}</span>
              </div>
            </div>
            
            <div className="hard-gates-section">
              <div className="gates-title">Hard Gates:</div>
              {signals.long?.hard_gates && (
                <>
                  <div className={`gate-item ${signals.long.hard_gates.ema_proximity?.pass ? 'pass' : 'fail'}`}>
                    <span className="gate-icon">{signals.long.hard_gates.ema_proximity?.pass ? '✓' : '✗'}</span>
                    <span>EMA Proximity (&lt;1%): {signals.long.hard_gates.ema_proximity?.detail || 'N/A'}</span>
                  </div>
                  <div className={`gate-item ${signals.long.hard_gates.spread?.pass ? 'pass' : 'fail'}`}>
                    <span className="gate-icon">{signals.long.hard_gates.spread?.pass ? '✓' : '✗'}</span>
                    <span>Spread (&lt;5 bps): {signals.long.hard_gates.spread?.detail || 'N/A'}</span>
                  </div>
                  <div className={`gate-item ${signals.long.hard_gates.directional_alignment?.pass ? 'pass' : 'fail'}`}>
                    <span className="gate-icon">{signals.long.hard_gates.directional_alignment?.pass ? '✓' : '✗'}</span>
                    <span>CVD/OBI Direction: {signals.long.hard_gates.directional_alignment?.detail || 'N/A'}</span>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
