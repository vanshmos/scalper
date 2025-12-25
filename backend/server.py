from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import asyncio
import logging
from contextlib import asynccontextmanager

from engine import Engine
from telegram_bot import TelegramNotifier

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

# Env
mongo_url = os.environ.get('MONGO_URL', "mongodb://localhost:27017")
db_name = os.environ.get('DB_NAME', "scalper_db")

# Components
telegram = TelegramNotifier()
engine = Engine(telegram_bot=telegram)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Engine...")
    asyncio.create_task(engine.start())
    # Start broadcaster
    asyncio.create_task(broadcast_state())
    yield
    # Shutdown
    engine.running = False
    logger.info("Engine Stopped")

app = FastAPI(lifespan=lifespan)
api_router = APIRouter(prefix="/api")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# WS Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                self.disconnect(connection)

manager = ConnectionManager()

import math
import numpy as np
import pandas as pd
from datetime import datetime

def clean_nans(obj):
    if obj is None:
        return None
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: clean_nans(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nans(v) for v in obj]
    elif isinstance(obj, (np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.float64, np.float32)):
        return clean_nans(float(obj))
    elif isinstance(obj, (datetime, pd.Timestamp)):
        return obj.isoformat()
    return obj

# Background Broadcaster
async def broadcast_state():
    while True:
        try:
            await asyncio.sleep(0.5) # 2Hz Update
            
            # Prepare Debug Info
            debug = {
                "candle_count_1m": len(engine.state.candles_1m),
                "candle_count_5m": len(engine.state.candles_5m),
                "candle_count_15m": len(engine.state.candles_15m),
                "trade_buffer_size": len(engine.state.trades),
                "oldest_trade": engine.state.trades[0]['time'] if len(engine.state.trades) > 0 else 0,
                "newest_trade": engine.state.trades[-1]['time'] if len(engine.state.trades) > 0 else 0,
                "backfill_error_msg": engine.state.backfill_error_msg,
                "ws_rate": engine.state.ws_rate,
                "last_candle_1m": engine.state.candles_1m.iloc[-1].to_dict() if not engine.state.candles_1m.empty else None,
                "last_candle_5m": engine.state.candles_5m.iloc[-1].to_dict() if not engine.state.candles_5m.empty else None,
            }

            state = {
                "price": engine.state.price,
                "regime": engine.state.regime,
                "trends": engine.state.trends, # Added trends to broadcast
                "gates_passed": engine.state.gates_passed,
                "indicators": engine.state.indicators,
                "signal_status": engine.signal_state.status,
                "forming_since": engine.signal_state.forming_since,
                "current_signal": engine.signal_state.current_signal,
                "warmup_progress": engine.state.warmup_progress,
                "is_warmed_up": engine.state.is_warmed_up,
                "backfill_error": engine.state.backfill_error,
                "backfill_failed_final": engine.state.backfill_failed_final,
                "debug": debug # Include debug info
            }
            
            # Clean NaNs and serialization issues before broadcasting
            cleaned_state = clean_nans(state)
            await manager.broadcast(cleaned_state)
        except Exception as e:
            logger.error(f"Broadcast error: {e}")
            await asyncio.sleep(1) # Prevent tight loop on error

@api_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text() # Keep alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@api_router.get("/health")
async def health():
    return {"status": "ok", "warmup": engine.state.warmup_progress}

app.include_router(api_router)
