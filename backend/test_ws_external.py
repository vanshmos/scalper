import asyncio
import websockets
import json
import ssl

async def test():
    # Use the EXTERNAL URL that fails in browser
    uri = "wss://dae3b1a8-0a33-4180-b590-545f41a018d4.preview.emergentagent.com/api/ws"
    print(f"Connecting to {uri}")
    
    # Create SSL context to verify certs (or ignore for testing)
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    try:
        async with websockets.connect(uri, ssl=ssl_context) as websocket:
            print("Connected!")
            msg = await websocket.recv()
            print(f"Received: {msg[:100]}...")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())
