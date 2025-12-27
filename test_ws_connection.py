#!/usr/bin/env python3
import asyncio
import websockets
import json

async def test_ws():
    try:
        async with websockets.connect('ws://localhost:8001/api/ws') as ws:
            print("✓ WebSocket connected")
            msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
            data = json.loads(msg)
            print(f"✓ Received data: price=${data.get('price', 'N/A')}, status={data.get('signal_status', 'N/A')}")
            return True
    except Exception as e:
        print(f"✗ WebSocket error: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_ws())
    exit(0 if result else 1)
