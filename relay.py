import asyncio, ssl, logging, pathlib, websockets
from websockets.legacy.server import serve     #  << use legacy protocol
from collections import defaultdict
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from threading import Thread

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")

ROOT = pathlib.Path(__file__).parent           # for static files
CERT = ROOT / "cert.pem"
KEY  = ROOT / "key.pem"

CLIENTS = defaultdict(set)                     # {"pub": {ws}, "sub": {ws}}

# ---------- WebSocket relay --------------------------------------------------
async def ws_handler(ws):                      # single arg — legacy protocol
    role = "pub" if ws.path == "/pub" else "sub"
    CLIENTS[role].add(ws)
    logging.info("%s CONNECTED as %s", ws.remote_address, role)

    try:
        async for chunk in ws:                 # binary WebM chunks
            if role == "pub":
                dead = []
                for v in CLIENTS["sub"]:
                    try:
                        await v.send(chunk)
                    except websockets.ConnectionClosed:
                        dead.append(v)
                for d in dead:
                    CLIENTS["sub"].discard(d)
    finally:
        CLIENTS[role].discard(ws)
        logging.info("%s DISCONNECTED", ws.remote_address)


# ---------- HTTPS static file server -----------------------------------------
def run_https_server():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):
            logging.info("%s - - %s", self.client_address[0], fmt % args)

    httpd = ThreadingHTTPServer(("", 8443), Handler)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    logging.info("HTTPS static server on :8443")
    httpd.serve_forever()


def main():
    # start static HTTPS site in a background thread
    Thread(target=run_https_server, daemon=True).start()

    # WSS relay
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(CERT, KEY)

    loop = asyncio.get_event_loop()
    wssrv = serve(ws_handler, "", 8765, ssl=ssl_ctx, max_size=2 ** 20)
    loop.run_until_complete(wssrv)
    logging.info("WSS relay on :8765")
    loop.run_forever()


if __name__ == "__main__":
    main()
