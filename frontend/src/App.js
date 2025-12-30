import { useEffect, useState } from "react";
import "@/App.css";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const WS_URL = BACKEND_URL.replace('https://', 'wss://').replace('http://', 'ws://');

function App() {
  const [status, setStatus] = useState(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);

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

  const indicators = status?.indicators || {};
  const regime = status?.regime || 'RANGING';
  const gates = status?.gates || {};
  const signals = status?.signals || {};
  const approximating = status?.approximating || {};

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
      <div className="header">
        <h1 className="title" data-testid="dashboard-title">BTC SCALPING ENGINE</h1>
        <div className="header-status">
          <div className={`status-indicator ${wsConnected ? 'connected' : 'disconnected'}`} data-testid="connection-indicator">
            <div className="status-dot"></div>
            <span>{wsConnected ? 'CONNECTED' : 'DISCONNECTED'}</span>
          </div>
          {lastUpdate && (
            <div className="last-update" data-testid="last-update">Updated: {lastUpdate}</div>
          )}
        </div>
      </div>

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
              <div className="indicator-title">EMA (1m)</div>
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
              <div className="indicator-title">EMA (5m)</div>
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
              <div className="indicator-title">EMA (15m)</div>
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
