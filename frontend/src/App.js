import { useEffect, useState, useRef } from "react";
import "@/App.css";
import TradeHistory from "@/components/TradeHistory";

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

  // Get data for active symbol
  const symbolData = status[activeSymbol] || {};
  const indicators = symbolData.indicators || {};
  const gates = symbolData.gates || {};
  const signals = symbolData.signals || {};
  const signalStatus = symbolData.signal_status || {};

  // Format symbol display name (remove -USDT-SWAP)
  const getDisplayName = (symbol) => {
    return symbol.toUpperCase();
  };

  return (
    <div className="app">
      {/* Audio element for alerts */}
      <audio ref={audioRef} src="/alert.mp3" preload="auto" />

      {/* Header */}
      <header className="header">
        <div className="header-content">
          <h1 className="title">SCALPING ENGINE</h1>
          <div className="header-right">
            <div className="connection-status">
              <div className={`status-dot ${wsConnected ? 'connected' : 'disconnected'}`}></div>
              <span className="status-text">{wsConnected ? 'LIVE' : 'OFFLINE'}</span>
            </div>
            {lastUpdate && <span className="last-update">{lastUpdate}</span>}
            <button 
              className={`audio-toggle ${audioMuted ? 'muted' : ''}`}
              onClick={() => setAudioMuted(!audioMuted)}
              title={audioMuted ? "Unmute alerts" : "Mute alerts"}
            >
              {audioMuted ? '🔇' : '🔊'}
            </button>
          </div>
        </div>
      </header>

      {/* Symbol Tabs */}
      <div className="symbol-tabs">
        {['btc', 'eth', 'sol'].map(symbol => (
          <button
            key={symbol}
            className={`symbol-tab ${activeSymbol === symbol ? 'active' : ''}`}
            onClick={() => setActiveSymbol(symbol)}
          >
            {getDisplayName(symbol)}
          </button>
        ))}
      </div>

      {/* Active Signal Banner - Only show if score >= 70 */}
      {signalStatus.state === 'ACTIVE' && signals[signalStatus.direction?.toLowerCase()]?.score >= 70 && (
        <div className={`signal-banner ${signalStatus.direction?.toLowerCase()}`}>
          <div className="signal-banner-content">
            <div className="signal-banner-left">
              <div className="signal-indicator">●</div>
              <div className="signal-info">
                <div className="signal-type-row">
                  <span className="signal-type">{signalStatus.direction} {getDisplayName(activeSymbol)}</span>
                  <span className={`signal-confidence confidence-${(signals[signalStatus.direction?.toLowerCase()]?.quality || 'low').toLowerCase()}`}>
                    {signals[signalStatus.direction?.toLowerCase()]?.quality || 'LOW'}
                  </span>
                </div>
                <span className="signal-label">ACTIVE • {Math.floor(signalStatus.active_remaining || 0)}s</span>
              </div>
            </div>
            <div className="signal-banner-details">
              <div className="signal-detail">
                <span className="label">Entry</span>
                <span className="value">{formatPrice(signalStatus.entry_min)}</span>
              </div>
              <div className="signal-detail">
                <span className="label">TP1</span>
                <span className="value tp">{formatPrice(signalStatus.tp1)}</span>
              </div>
              <div className="signal-detail">
                <span className="label">TP2</span>
                <span className="value tp">{formatPrice(signalStatus.tp2)}</span>
              </div>
              <div className="signal-detail">
                <span className="label">Stop Loss</span>
                <span className="value sl">{formatPrice(signalStatus.stop_loss)}</span>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="main-content">
        {/* Price & Regime */}
        <div className="price-section">
          <div className="price-display">
            <span className="price-label">{getDisplayName(activeSymbol)} PRICE</span>
            <span className="price-value">{formatPrice(symbolData.current_price)}</span>
          </div>
          <div className="regime-badge">
            <span className="regime-label">REGIME</span>
            <span className={`regime-value regime-${symbolData.regime?.toLowerCase()}`}>
              {symbolData.regime || 'UNKNOWN'}
            </span>
          </div>
        </div>

        {/* Market Health Cards */}
        <div className="health-grid">
          <div className="health-card">
            <div className="health-header">
              <span>CANDLES</span>
            </div>
            <div className="health-stats">
              <div className="stat">
                <span className="stat-value">{symbolData.candle_counts?.['1m'] || 0}</span>
                <span className="stat-label">1m</span>
              </div>
              <div className="stat">
                <span className="stat-value">{symbolData.candle_counts?.['5m'] || 0}</span>
                <span className="stat-label">5m</span>
              </div>
              <div className="stat">
                <span className="stat-value">{symbolData.candle_counts?.['15m'] || 0}</span>
                <span className="stat-label">15m</span>
              </div>
            </div>
          </div>

          <div className="health-card">
            <div className="health-header">
              <span>GATES</span>
              <span className={`gate-status ${gates.all_pass ? 'pass' : 'fail'}`}>
                {gates.all_pass ? '✓ PASS' : '✗ FAIL'}
              </span>
            </div>
            <div className="health-stats">
              <div className="stat">
                <span className="stat-label">Spread</span>
                <span className={`stat-value ${gates.spread?.pass ? 'text-green' : 'text-red'}`}>
                  {formatNumber(gates.spread?.value, 2)} bps
                </span>
              </div>
              <div className="stat">
                <span className="stat-label">Depth</span>
                <span className={`stat-value ${gates.depth?.pass ? 'text-green' : 'text-red'}`}>
                  ${(gates.depth?.value / 1000000).toFixed(1)}M
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Indicators Grid */}
        <div className="indicators-grid">
          <div className="indicator-card">
            <span className="indicator-label">EMA 20/50 (5m)</span>
            <span className="indicator-value">
              {formatNumber(indicators.ema?.['5m']?.ema20, 2)} / {formatNumber(indicators.ema?.['5m']?.ema50, 2)}
            </span>
          </div>
          <div className="indicator-card">
            <span className="indicator-label">RSI (5m)</span>
            <span className={`indicator-value ${indicators.rsi_5m < 30 ? 'text-red' : indicators.rsi_5m > 70 ? 'text-green' : ''}`}>
              {formatNumber(indicators.rsi_5m, 0)}
            </span>
          </div>
          <div className="indicator-card">
            <span className="indicator-label">ATR (5m)</span>
            <span className="indicator-value">{formatNumber(indicators.atr_5m, 2)}</span>
          </div>
          <div className="indicator-card">
            <span className="indicator-label">CVD (5m)</span>
            <span className={`indicator-value ${indicators.cvd?.['5m'] > 0 ? 'text-green' : 'text-red'}`}>
              {formatNumber(indicators.cvd?.['5m'], 3)}
            </span>
          </div>
          <div className="indicator-card">
            <span className="indicator-label">OBI</span>
            <span className={`indicator-value ${indicators.obi > 0 ? 'text-green' : 'text-red'}`}>
              {formatNumber(indicators.obi, 3)}
            </span>
          </div>
          <div className="indicator-card">
            <span className="indicator-label">VWAP</span>
            <span className="indicator-value">{formatPrice(indicators.vwap)}</span>
          </div>
        </div>

        {/* Signal Scores - Side by Side */}
        <div className="signals-section">
          <div className="signals-header">SIGNAL SCORES</div>
          <div className="signals-scores">
            <div className="score-card short">
              <div className="score-header">SHORT</div>
              <div className="score-display">
                <span className="score-value">{signals.short?.score || 0}</span>
                <span className="score-max">/100</span>
              </div>
              <div className={`score-quality quality-${signals.short?.quality?.toLowerCase()}`}>
                {signals.short?.quality || 'LOW'}
              </div>
            </div>
            <div className="score-card long">
              <div className="score-header">LONG</div>
              <div className="score-display">
                <span className="score-value">{signals.long?.score || 0}</span>
                <span className="score-max">/100</span>
              </div>
              <div className={`score-quality quality-${signals.long?.quality?.toLowerCase()}`}>
                {signals.long?.quality || 'LOW'}
              </div>
            </div>
          </div>

          {/* Common Criteria */}
          <div className="criteria-section">
            <div className="criteria-header">MARKET CONDITIONS</div>
            <div className="criteria-grid">
              {signals.long?.hard_gates && (
                <>
                  <div className={`criteria-item ${signals.long.hard_gates.rsi_filter?.pass ? 'pass' : 'fail'}`}>
                    <span className="criteria-icon">{signals.long.hard_gates.rsi_filter?.pass ? '✓' : '✗'}</span>
                    <span className="criteria-label">RSI Range</span>
                    <span className="criteria-value">{signals.long.hard_gates.rsi_filter?.detail}</span>
                  </div>
                  <div className={`criteria-item ${signals.long.hard_gates.spread?.pass ? 'pass' : 'fail'}`}>
                    <span className="criteria-icon">{signals.long.hard_gates.spread?.pass ? '✓' : '✗'}</span>
                    <span className="criteria-label">Spread</span>
                    <span className="criteria-value">{signals.long.hard_gates.spread?.detail}</span>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Direction-Specific Filters */}
          <div className="direction-filters">
            <div className="filter-column">
              <div className="filter-header">SHORT FILTERS</div>
              {signals.short?.hard_gates && (
                <>
                  <div className={`criteria-item ${signals.short.hard_gates.regime_filter?.pass ? 'pass' : 'fail'}`}>
                    <span className="criteria-icon">{signals.short.hard_gates.regime_filter?.pass ? '✓' : '✗'}</span>
                    <span className="criteria-label">Regime</span>
                    <span className="criteria-value">{signals.short.hard_gates.regime_filter?.detail}</span>
                  </div>
                  <div className={`criteria-item ${signals.short.hard_gates['cvd/obi_alignment']?.pass ? 'pass' : 'fail'}`}>
                    <span className="criteria-icon">{signals.short.hard_gates['cvd/obi_alignment']?.pass ? '✓' : '✗'}</span>
                    <span className="criteria-label">Flow</span>
                    <span className="criteria-value">{signals.short.hard_gates['cvd/obi_alignment']?.detail}</span>
                  </div>
                </>
              )}
            </div>
            <div className="filter-column">
              <div className="filter-header">LONG FILTERS</div>
              {signals.long?.hard_gates && (
                <>
                  <div className={`criteria-item ${signals.long.hard_gates.regime_filter?.pass ? 'pass' : 'fail'}`}>
                    <span className="criteria-icon">{signals.long.hard_gates.regime_filter?.pass ? '✓' : '✗'}</span>
                    <span className="criteria-label">Regime</span>
                    <span className="criteria-value">{signals.long.hard_gates.regime_filter?.detail}</span>
                  </div>
                  <div className={`criteria-item ${signals.long.hard_gates['cvd/obi_alignment']?.pass ? 'pass' : 'fail'}`}>
                    <span className="criteria-icon">{signals.long.hard_gates['cvd/obi_alignment']?.pass ? '✓' : '✗'}</span>
                    <span className="criteria-label">Flow</span>
                    <span className="criteria-value">{signals.long.hard_gates['cvd/obi_alignment']?.detail}</span>
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
