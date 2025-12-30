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
        <h1 className="title" data-testid="dashboard-title">BTC SCALPING ENGINE</h1>
        <div className="header-status">
          <div className={`status-indicator ${wsConnected ? 'connected' : 'disconnected'}`} data-testid="connection-indicator">
            <div className="status-dot"></div>
            <span>{wsConnected ? 'CONNECTED' : 'DISCONNECTED'}</span>
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

      {/* Active Signal Card - Only show when FORMING or ACTIVE */}
      {(signalStatus.state === 'FORMING' || signalStatus.state === 'ACTIVE') && (
        <div className="active-signal-card" data-testid="active-signal-card">
          <div className="signal-card-header">
            <div className={`signal-direction ${signalStatus.direction?.toLowerCase()}`}>
              {signalStatus.direction === 'SHORT' ? '🔴' : '🟢'} {signalStatus.direction} SIGNAL
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
              <div className="section-label">CURRENT PRICE</div>
              <div className="price-display" data-testid="current-price">
                {status?.current_price ? formatPrice(status.current_price) : '—'}
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
          <div className="card-header">OKX CONNECTION</div>
          <div className="card-content">
            <div className="info-row">
              <span className="info-label">WebSocket Status:</span>
              <span className={`info-value ${status?.connected ? 'text-green' : 'text-red'}`} data-testid="okx-status">
                {status?.connected ? 'CONNECTED' : 'DISCONNECTED'}
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">Last Update:</span>
              <span className="info-value" data-testid="last-okx-update">
                {status?.last_update ? new Date(status.last_update).toLocaleTimeString() : '—'}
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
                {status?.candle_counts?.['1m'] ?? '—'}
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">5m Candles:</span>
              <span className="info-value text-green" data-testid="candles-5m">
                {status?.candle_counts?.['5m'] ?? '—'}
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">15m Candles:</span>
              <span className="info-value text-green" data-testid="candles-15m">
                {status?.candle_counts?.['15m'] ?? '—'}
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
          <div className="card-header">PHASE 4: SHORT SIGNAL</div>
          <div className="card-content">
            <div className="confidence-row">
              <span>Confidence:</span>
              <span className={`confidence-value ${signals.short?.confidence >= 70 ? 'text-green' : 'text-red'}`} data-testid="short-confidence">
                {signals.short?.confidence || 0}/100
              </span>
            </div>
            
            <div className="checklist">
              <div className={`checklist-item ${signals.short?.checklist?.regime?.pass ? 'pass' : 'fail'}`} data-testid="short-regime">
                <span className="check-icon">{signals.short?.checklist?.regime?.pass ? '✓' : '✗'}</span>
                <span>{signals.short?.checklist?.regime?.description || 'Regime check'}</span>
              </div>
              <div className={`checklist-item ${signals.short?.checklist?.structure?.pass ? 'pass' : 'fail'}`} data-testid="short-structure">
                <span className="check-icon">{signals.short?.checklist?.structure?.pass ? '✓' : '✗'}</span>
                <span>{signals.short?.checklist?.structure?.description || 'Structure check'}</span>
              </div>
              <div className={`checklist-item ${signals.short?.checklist?.cvd?.pass ? 'pass' : 'fail'}`} data-testid="short-cvd">
                <span className="check-icon">{signals.short?.checklist?.cvd?.pass ? '✓' : '✗'}</span>
                <span>{signals.short?.checklist?.cvd?.description || 'CVD check'}</span>
              </div>
              <div className={`checklist-item ${signals.short?.checklist?.obi?.pass ? 'pass' : 'fail'}`} data-testid="short-obi">
                <span className="check-icon">{signals.short?.checklist?.obi?.pass ? '✓' : '✗'}</span>
                <span>{signals.short?.checklist?.obi?.description || 'OBI check'}</span>
              </div>
              <div className={`checklist-item ${signals.short?.checklist?.pullback?.pass ? 'pass' : 'fail'}`} data-testid="short-pullback">
                <span className="check-icon">{signals.short?.checklist?.pullback?.pass ? '✓' : '✗'}</span>
                <span>{signals.short?.checklist?.pullback?.description || 'Pullback check'}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Signal Checklist - LONG */}
        <div className="info-card signal-card">
          <div className="card-header">PHASE 4: LONG SIGNAL</div>
          <div className="card-content">
            <div className="confidence-row">
              <span>Confidence:</span>
              <span className={`confidence-value ${signals.long?.confidence >= 70 ? 'text-green' : 'text-red'}`} data-testid="long-confidence">
                {signals.long?.confidence || 0}/100
              </span>
            </div>
            
            <div className="checklist">
              <div className={`checklist-item ${signals.long?.checklist?.regime?.pass ? 'pass' : 'fail'}`} data-testid="long-regime">
                <span className="check-icon">{signals.long?.checklist?.regime?.pass ? '✓' : '✗'}</span>
                <span>{signals.long?.checklist?.regime?.description || 'Regime check'}</span>
              </div>
              <div className={`checklist-item ${signals.long?.checklist?.structure?.pass ? 'pass' : 'fail'}`} data-testid="long-structure">
                <span className="check-icon">{signals.long?.checklist?.structure?.pass ? '✓' : '✗'}</span>
                <span>{signals.long?.checklist?.structure?.description || 'Structure check'}</span>
              </div>
              <div className={`checklist-item ${signals.long?.checklist?.cvd?.pass ? 'pass' : 'fail'}`} data-testid="long-cvd">
                <span className="check-icon">{signals.long?.checklist?.cvd?.pass ? '✓' : '✗'}</span>
                <span>{signals.long?.checklist?.cvd?.description || 'CVD check'}</span>
              </div>
              <div className={`checklist-item ${signals.long?.checklist?.obi?.pass ? 'pass' : 'fail'}`} data-testid="long-obi">
                <span className="check-icon">{signals.long?.checklist?.obi?.pass ? '✓' : '✗'}</span>
                <span>{signals.long?.checklist?.obi?.description || 'OBI check'}</span>
              </div>
              <div className={`checklist-item ${signals.long?.checklist?.pullback?.pass ? 'pass' : 'fail'}`} data-testid="long-pullback">
                <span className="check-icon">{signals.long?.checklist?.pullback?.pass ? '✓' : '✗'}</span>
                <span>{signals.long?.checklist?.pullback?.description || 'Pullback check'}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
