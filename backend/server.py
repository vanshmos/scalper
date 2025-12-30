from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
import logging
import asyncio
import json
from pathlib import Path
from signal_engine import SignalEngine
from bybit_client import OKXWebSocketClient

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
symbols = ['BTC', 'ETH', 'SOL']
signal_engines = {}
ws_client: OKXWebSocketClient = None
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
    """Start all signal engines on app startup"""
    global signal_engines, ws_client, engine_task
    
    logger.info(f"Starting signal engines for {len(symbols)} symbols...")
    
    # Create signal engines for each symbol
    for symbol in symbols:
        signal_engines[symbol] = SignalEngine(symbol)
        await signal_engines[symbol].start()
    
    # Create single WebSocket client for all symbols
    ws_client = OKXWebSocketClient(
        on_orderbook=route_orderbook,
        on_trade=route_trade,
        on_ticker=route_ticker
    )
    
    # Start WebSocket client
    engine_task = asyncio.create_task(ws_client.start())
    
    logger.info(f"All {len(symbols)} signal engines started")

@app.on_event("shutdown")
async def shutdown_event():
    """Stop all signal engines on app shutdown"""
    global signal_engines, ws_client, engine_task
    
    logger.info("Stopping all signal engines...")
    
    for symbol, engine in signal_engines.items():
        await engine.stop()
    
    if ws_client:
        await ws_client.stop()
    
    if engine_task:
        engine_task.cancel()
        try:
            await engine_task
        except asyncio.CancelledError:
            pass

@app.get("/api/status")
async def get_status():
    """Get current status for all engines"""
    status = {}
    for symbol, engine in signal_engines.items():
        status[symbol.lower()] = engine.get_status()
    return status

@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await websocket.accept()
    logger.info("WebSocket client connected")
    
    try:
        while True:
            if signal_engine:
                status = signal_engine.get_status()
                await websocket.send_text(json.dumps(status))
            await asyncio.sleep(0.5)  # Send updates every 500ms
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
