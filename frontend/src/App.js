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
          <div className="section-label">CURRENT PRICE</div>
          <div className="price-display" data-testid="current-price">
            {status?.current_price ? formatPrice(status.current_price) : '—'}
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
      </div>
    </div>
  );
}

export default App;
