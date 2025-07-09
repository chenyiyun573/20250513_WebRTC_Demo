# stream-relay/relay.py
import asyncio, ssl, logging, pathlib, websockets, http.server, socketserver
from collections import defaultdict

logging.basicConfig(level=logging.INFO)
CLIENTS = defaultdict(set)            # {"pub": {ws}, "sub": {ws}}

# ---------- WebSocket relay -------------------------------------------------
async def ws_handler(ws):
    role = "pub" if ws.path == "/pub" else "sub"
    CLIENTS[role].add(ws)
    logging.info("%s connected (%s)", ws.remote_address, role)

    try:
        async for msg in ws:
            if role == "pub":
                dead = []
                for v in CLIENTS["sub"]:
                    try:
                        await v.send(msg)
                    except websockets.ConnectionClosed:
                        dead.append(v)
                for d in dead:
                    CLIENTS["sub"].discard(d)
    finally:
        CLIENTS[role].discard(ws)
        logging.info("%s left", ws.remote_address)


# ---------- HTTPS static file server ----------------------------------------
class TLSHTTPServer(socketserver.TCPServer):
    allow_reuse_address = True

def start_https(loop, ssl_ctx):
    handler = http.server.SimpleHTTPRequestHandler
    # Serve files from /app (where publisher.html sits)
    httpd = TLSHTTPServer(("", 8443), handler)
    httpd.socket = ssl_ctx.wrap_socket(httpd.socket, server_side=True)
    loop.run_in_executor(None, httpd.serve_forever)
    logging.info("HTTPS static server on :8443")

# ---------- Main ------------------------------------------------------------
def main():
    ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_ctx.load_cert_chain("cert.pem", "key.pem")

    async def run_servers():
        # 1. start HTTPS static server in thread
        loop = asyncio.get_running_loop()
        start_https(loop, ssl_ctx)
        # 2. start WSS relay
        await websockets.serve(
            ws_handler, "", 8765, ssl=ssl_ctx, max_size=2**20)
        logging.info("WSS relay on :8765")
        await asyncio.Future()   # run forever

    asyncio.run(run_servers())


if __name__ == "__main__":
    main()
