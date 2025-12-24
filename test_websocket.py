import asyncio
import websockets
import json

async def test_websocket():
    uri = "wss://dae3b1a8-0a33-4180-b590-545f41a018d4.preview.emergentagent.com/api/ws"
    print(f"Connecting to: {uri}")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ WebSocket connected successfully!")
            
            # Send a keep-alive message
            await websocket.send("ping")
            print("📤 Sent ping message")
            
            # Wait for messages for 10 seconds
            print("⏳ Waiting for messages...")
            try:
                for i in range(20):  # Wait up to 10 seconds (0.5s intervals)
                    message = await asyncio.wait_for(websocket.recv(), timeout=0.5)
                    data = json.loads(message)
                    print(f"📨 Received message {i+1}: {json.dumps(data, indent=2)}")
                    if i >= 2:  # Show first 3 messages
                        break
            except asyncio.TimeoutError:
                print("⏰ No more messages received")
            
    except Exception as e:
        print(f"❌ WebSocket connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_websocket())