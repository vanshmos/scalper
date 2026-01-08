from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
import logging
import asyncio
import json
from pathlib import Path
from signal_engine_v2 import SignalEngine
from trade_tracker import get_all_recent_trades, get_aggregate_stats, migrate_trades_to_capital_based

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create the main app
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Multi-symbol signal engines
SYMBOLS = {
    'BTC': 'BTC-USDT-SWAP',
    'ETH': 'ETH-USDT-SWAP',
    'SOL': 'SOL-USDT-SWAP'
}
signal_engines = {}
engine_tasks = []

async def route_orderbook(symbol: str, data: dict):
    """Route orderbook data to appropriate engine"""
    if symbol in signal_engines:
        await signal_engines[symbol].on_orderbook(data)

async def route_trade(symbol: str, trade: dict):
    """Route trade data to appropriate engine"""
    if symbol in signal_engines:
        await signal_engines[symbol].on_trade(trade)

async def route_ticker(symbol: str, data: dict):
    """Route ticker data to appropriate engine"""
    if symbol in signal_engines:
        await signal_engines[symbol].on_ticker(data)

@app.on_event("startup")
async def startup_event():
    """Start all signal engines on app startup"""
    global signal_engines, engine_tasks
    
    logger.info(f"Starting signal engines for {len(SYMBOLS)} symbols...")
    
    # Create and start engines for each symbol
    for display_name, okx_symbol in SYMBOLS.items():
        engine = SignalEngine(okx_symbol, display_name)
        signal_engines[display_name.lower()] = engine
        await engine.start()
    
    logger.info(f"All {len(SYMBOLS)} signal engines started successfully")

@app.on_event("shutdown")
async def shutdown_event():
    """Stop all signal engines on app shutdown"""
    global signal_engines, engine_tasks
    
    logger.info("Stopping all signal engines...")
    
    # CRITICAL: Save state for all engines before shutdown (anti-amnesia)
    logger.info("Saving state for all engines before shutdown...")
    for display_name, engine in signal_engines.items():
        try:
            await engine.save_state()
            logger.info(f"{display_name}: State saved successfully on shutdown")
        except Exception as e:
            logger.error(f"{display_name}: Error saving state on shutdown: {e}")
    
    # Stop WebSocket connections
    for engine in signal_engines.values():
        await engine.ws_client.stop()
    
    # Cancel periodic save tasks
    for task in engine_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    
    logger.info("All signal engines stopped and state saved")

@app.get("/api/status")
async def get_status():
    """Get current status for all engines"""
    status = {}
    for display_name, engine in signal_engines.items():
        status[display_name] = engine.get_status()
    return status

@app.get("/api/test-telegram")
async def test_telegram():
    """Test Telegram alert - sends a test message"""
    try:
        from alerts import AlertManager
        alert_manager = AlertManager()
        
        if alert_manager.telegram_enabled:
            alert_manager.send_signal_alert(
                direction="SHORT",
                confidence=100,
                entry=92500.00,
                stop_loss=92750.00,
                tp1=92000.00,
                tp2=91500.00,
                symbol="BTC-TEST"
            )
            return {"status": "success", "message": "Test alert sent to Telegram"}
        else:
            return {"status": "error", "message": "Telegram not configured"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/trades")
async def get_trades(limit: int = 50):
    """
    Get recent trades across all symbols for the Trade Accountability System.
    Returns trade history with outcomes, P&L, and MFE/MAE metrics.
    """
    try:
        trades = get_all_recent_trades(limit=limit)
        stats = get_aggregate_stats()
        
        return {
            "trades": trades,
            "stats": stats,
            "count": len(trades)
        }
    except Exception as e:
        logger.error(f"Error getting trades: {e}")
        return {"trades": [], "stats": {}, "count": 0, "error": str(e)}

@app.get("/api/trades/{symbol}")
async def get_trades_by_symbol(symbol: str, limit: int = 50):
    """Get recent trades for a specific symbol"""
    try:
        symbol_key = symbol.lower()
        if symbol_key in signal_engines:
            trades = signal_engines[symbol_key].tracker.get_recent_trades(limit=limit)
            stats = signal_engines[symbol_key].tracker.get_stats()
            return {
                "symbol": symbol.upper(),
                "trades": trades,
                "stats": stats,
                "count": len(trades)
            }
        else:
            return {"error": f"Symbol {symbol} not found", "trades": [], "stats": {}}
    except Exception as e:
        logger.error(f"Error getting trades for {symbol}: {e}")
        return {"trades": [], "stats": {}, "error": str(e)}

@app.post("/api/trades/migrate")
async def migrate_trades():
    """
    Migrate existing trades to capital-based P&L calculations.
    Recalculates all P&L and MFE/MAE values based on $100,000 capital.
    """
    try:
        result = migrate_trades_to_capital_based()
        return result
    except Exception as e:
        logger.error(f"Error migrating trades: {e}")
        return {"status": "error", "message": str(e)}

@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await websocket.accept()
    logger.info("WebSocket client connected")
    
    try:
        while True:
            # Send current status for all engines
            status = {}
            for display_name, engine in signal_engines.items():
                status[display_name] = engine.get_status()
            await websocket.send_text(json.dumps(status))
            await asyncio.sleep(0.5)  # Send updates every 500ms
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
