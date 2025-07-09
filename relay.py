import asyncio, websockets, logging, ssl
from collections import defaultdict

logging.basicConfig(level=logging.INFO)

CLIENTS = defaultdict(set)          # {"pub": {ws}, "sub": {ws}}

async def handler(ws, path):
    role = "sub"
    if path == "/pub":
        role = "pub"
    CLIENTS[role].add(ws)
    logging.info("%s connected as %s", ws.remote_address, role)

    try:
        async for message in ws:              # binary WebM chunks
            if role == "pub":
                dead = []
                for v in CLIENTS["sub"]:
                    try:
                        await v.send(message)
                    except websockets.ConnectionClosed:
                        dead.append(v)
                for d in dead:
                    CLIENTS["sub"].discard(d)
    finally:
        CLIENTS[role].discard(ws)
        logging.info("%s left", ws.remote_address)

def main():
    ssl_ctx = None            # comment‑in for HTTPS/WSS
    # ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    # ssl_ctx.load_cert_chain("cert.pem", "key.pem")

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        websockets.serve(handler, "", 8765,
                         ssl=ssl_ctx, max_size=2**20))   # ~1 MB
    logging.info("Relay running on port 8765 (%s)",
                 "wss" if ssl_ctx else "ws")
    loop.run_forever()

if __name__ == "__main__":
    main()
