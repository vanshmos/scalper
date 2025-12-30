from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
import logging
import asyncio
import json
from pathlib import Path
from signal_engine import SignalEngine

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

# Signal engine instance
signal_engine: SignalEngine = None
engine_task: asyncio.Task = None

@app.on_event("startup")
async def startup_event():
    """Start the signal engine on app startup"""
    global signal_engine, engine_task
    logger.info("Starting signal engine...")
    signal_engine = SignalEngine()
    engine_task = asyncio.create_task(signal_engine.start())

@app.on_event("shutdown")
async def shutdown_event():
    """Stop the signal engine on app shutdown"""
    global signal_engine, engine_task
    if signal_engine:
        logger.info("Stopping signal engine...")
        await signal_engine.stop()
    if engine_task:
        engine_task.cancel()
        try:
            await engine_task
        except asyncio.CancelledError:
            pass

@app.get("/api/status")
async def get_status():
    """Get current engine status"""
    if signal_engine:
        return signal_engine.get_status()
    return {'error': 'Engine not initialized'}

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
