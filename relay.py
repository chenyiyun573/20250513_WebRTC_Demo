# stream-relay/relay.py
import asyncio, ssl, logging, pathlib, websockets, http.server, socketserver
from collections import defaultdict

logging.basicConfig(level=logging.INFO)
CLIENTS = defaultdict(set)            # {"pub": {ws}, "sub": {ws}}

# ---------- WebSocket relay -------------------------------------------------
async def ws_handler(ws, path):
    role = "pub" if path == "/pub" else "sub"
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

    loop = asyncio.get_event_loop()
    # 1‑ start HTTPS for static files
    start_https(loop, ssl_ctx)
    # 2‑ start WSS relay (max chunk 1 MB)
    wssrv = websockets.serve(
        ws_handler, "", 8765, ssl=ssl_ctx, max_size=2**20)
    loop.run_until_complete(wssrv)
    logging.info("WSS relay on :8765")
    loop.run_forever()

if __name__ == "__main__":
    main()
