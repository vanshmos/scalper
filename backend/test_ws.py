import asyncio
import websockets
import json

async def test():
    uri = "ws://localhost:8001/api/ws"
    print(f"Connecting to {uri}")
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected!")
            msg = await websocket.recv()
            print(f"Received: {msg[:100]}...")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())
