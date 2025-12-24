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

# Background Broadcaster
async def broadcast_state():
    while True:
        await asyncio.sleep(0.5) # 2Hz Update
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
            "backfill_error": engine.state.backfill_error
        }
        await manager.broadcast(state)

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
