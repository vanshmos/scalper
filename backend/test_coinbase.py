import asyncio
import websockets
import json

async def test():
    uri = "wss://ws-feed.exchange.coinbase.com"
    print(f"Connecting to {uri}")
    async with websockets.connect(uri) as websocket:
        print("Connected!")
        msg = {
            "type": "subscribe",
            "product_ids": ["BTC-USD"],
            "channels": ["ticker", "level2_batch"]
        }
        await websocket.send(json.dumps(msg))
        print("Subscribed!")
        
        for i in range(5):
            res = await websocket.recv()
            print(f"Msg {i}: {res[:100]}")

if __name__ == "__main__":
    asyncio.run(test())
