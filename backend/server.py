from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
import logging
import asyncio
import json
from pathlib import Path
from btc_engine import BTCSignalEngine

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

# BTC-only signal engine
btc_engine: BTCSignalEngine = None
engine_task: asyncio.Task = None

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
    """Start BTC signal engine on app startup"""
    global btc_engine, engine_task
    
    logger.info("Starting BTC signal engine...")
    
    # Create and start BTC engine
    btc_engine = BTCSignalEngine("BTC-USDT-SWAP")
    await btc_engine.start()
    
    logger.info("BTC signal engine started successfully")

@app.on_event("shutdown")
async def shutdown_event():
    """Stop signal engine on app shutdown"""
    global btc_engine, engine_task
    
    logger.info("Stopping BTC signal engine...")
    
    if btc_engine:
        await btc_engine.ws_client.stop()
    
    if engine_task:
        engine_task.cancel()
        try:
            await engine_task
        except asyncio.CancelledError:
            pass

@app.get("/api/status")
async def get_status():
    """Get current status for BTC engine"""
    if btc_engine:
        return {"btc": btc_engine.get_status()}
    return {"error": "Engine not initialized"}

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
                symbol="BTC-USDT-SWAP"
            )
            return {"status": "success", "message": "Test alert sent to Telegram"}
        else:
            return {"status": "error", "message": "Telegram not configured"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await websocket.accept()
    logger.info("WebSocket client connected")
    
    try:
        while True:
            status = {}
            for symbol, engine in signal_engines.items():
                status[symbol.lower()] = engine.get_status()
            await websocket.send_text(json.dumps(status))
            await asyncio.sleep(0.5)  # Send updates every 500ms
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
