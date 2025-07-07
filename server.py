#!/usr/bin/env python3
# server.py  –  2025‑07‑07 consolidated troubleshooting edition

import asyncio
import json
import logging
import os
import random
import ssl
import uuid
from typing import Optional

from aiohttp import web
from aiortc import (
    RTCIceCandidate,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.contrib.media import MediaRelay
from aiortc.sdp import candidate_from_sdp     # ← correct module
import aioice   # for port‑range patch

# ---------------------------------------------------------------------------
# 0.  Logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webrtc_server")

# ---------------------------------------------------------------------------
# 1.  Limit ICE ports to a narrow UDP range if requested
# ---------------------------------------------------------------------------

default_range = "50000,50050"                     # fallback
env_range = os.getenv("AIORTC_ICE_PORT_RANGE", default_range)

try:
    port_lo, port_hi = map(int, env_range.split(","))
    assert 0 < port_lo < port_hi < 65536
    aioice.random_port = lambda: random.randint(port_lo, port_hi)
    logger.info(f"ICE UDP port range set to {port_lo}-{port_hi}")
except Exception as exc:
    logger.error(f"Invalid AIORTC_ICE_PORT_RANGE='{env_range}': {exc}")
    raise SystemExit(1)

# ---------------------------------------------------------------------------
# 2.  Paths and globals
# ---------------------------------------------------------------------------

ROOT        = os.path.dirname(__file__)
CERTS_DIR   = os.path.join(ROOT, "certs")

pcs         : set[RTCPeerConnection] = set()
relay       = MediaRelay()
publisher_tracks = {"audio": None, "video": None}

# ---------------------------------------------------------------------------
# 3.  Static file helpers
# ---------------------------------------------------------------------------

async def serve_file(request: web.Request, name: str, mime: str):
    try:
        with open(os.path.join(ROOT, name), "r") as f:
            return web.Response(text=f.read(), content_type=mime)
    except FileNotFoundError:
        return web.Response(status=404, text="Not found")

async def publisher_page(request):  return await serve_file(request, "publisher.html", "text/html")
async def viewer_page(request):     return await serve_file(request, "viewer.html",    "text/html")
async def client_js(request):       return await serve_file(request, "client.js",      "application/javascript")

# ---------------------------------------------------------------------------
# 4.  WebSocket / signalling
# ---------------------------------------------------------------------------

async def websocket_handler(request: web.Request):
    ws         = web.WebSocketResponse()
    await ws.prepare(request)

    client_id  = str(uuid.uuid4())
    pc = RTCPeerConnection({
        "iceServers": [
            {"urls": "stun:stun.l.google.com:19302"}
        ]
    })

    client_role: Optional[str] = None

    logger.info(f"WS client {client_id} connected")

    pcs.add(pc)           # track for shutdown

    # ICE → browser
    @pc.on("icecandidate")
    async def on_icecandidate(cand):
        if cand:
            await ws.send_json({"type": "candidate", "candidate": cand.to_json()})

    # Track from publisher
    @pc.on("track")
    async def on_track(track):
        logger.info(f"{client_id} ({client_role}) track {track.kind} received")
        if client_role == "publisher":
            publisher_tracks[track.kind] = relay.subscribe(track) if track.kind == "video" else track

    # Connection‑state changes
    @pc.on("connectionstatechange")
    async def on_state():
        logger.info(f"PC {client_id} state {pc.connectionState}")
        if pc.connectionState in ("failed", "closed", "disconnected"):
            await cleanup()

    async def cleanup():
        if pc in pcs:
            await pc.close()
            pcs.discard(pc)
        if client_role == "publisher":
            publisher_tracks["audio"] = None
            publisher_tracks["video"] = None
        if not ws.closed:
            await ws.close()
        logger.info(f"Client {client_id} cleaned up")

    # ---------------- main WS loop ----------------
    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)

            # ---- role selection
            if data["type"] == "role":
                client_role = data["role"]
                logger.info(f"{client_id} set role {client_role}")

                if client_role == "subscriber":
                    # pre‑declare recvonly transceivers
                    pc.addTransceiver("audio", direction="recvonly")
                    pc.addTransceiver("video", direction="recvonly")
                    # attach already‑present tracks if any
                    if publisher_tracks["audio"]:
                        pc.addTrack(publisher_tracks["audio"])
                    if publisher_tracks["video"]:
                        pc.addTrack(publisher_tracks["video"])

                    offer = await pc.createOffer()
                    await pc.setLocalDescription(offer)
                    await ws.send_json({"type": "offer", "sdp": offer.sdp})

            # ---- publisher → offer
            elif data["type"] == "offer":
                offer = RTCSessionDescription(sdp=data["sdp"], type="offer")
                await pc.setRemoteDescription(offer)
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)
                await ws.send_json({"type": "answer", "sdp": answer.sdp})

            # ---- subscriber → answer
            elif data["type"] == "answer":
                answer = RTCSessionDescription(sdp=data["sdp"], type="answer")
                await pc.setRemoteDescription(answer)

            # ---- trickle ICE
            elif data["type"] == "candidate":
                cand = data["candidate"]          # dict from browser
                if cand and cand.get("candidate"):
                    ice = candidate_from_sdp(cand["candidate"])
                    ice.sdpMid        = cand.get("sdpMid")
                    ice.sdpMLineIndex = cand.get("sdpMLineIndex")
                    try:
                        await pc.addIceCandidate(ice)
                    except Exception as exc:
                        logger.warning(f"addIceCandidate failed: {exc}")

            # ---- hang‑up
            elif data["type"] == "hangup":
                await cleanup()
                break

    except Exception as exc:
        logger.exception(f"WS handler error: {exc}")
        await cleanup()

    return ws

# ---------------------------------------------------------------------------
# 5.  Shutdown hook
# ---------------------------------------------------------------------------

async def on_shutdown(app):
    coros = [pc.close() for pc in list(pcs)]
    await asyncio.gather(*coros, return_exceptions=True)
    pcs.clear()
    logger.info("Server shutdown – all PCs closed")

# ---------------------------------------------------------------------------
# 6.  App bootstrap
# ---------------------------------------------------------------------------

app = web.Application()
app.on_shutdown.append(on_shutdown)

app.add_routes([
    web.get("/",          viewer_page),
    web.get("/viewer",    viewer_page),
    web.get("/publisher", publisher_page),
    web.get("/client.js", client_js),
    web.get("/ws",        websocket_handler),
])

if __name__ == "__main__":
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(os.path.join(CERTS_DIR, "server.crt"),
                            os.path.join(CERTS_DIR, "server.key"))
    logger.info("Starting HTTPS signalling server on :8080")
    web.run_app(app, host="0.0.0.0", port=8080, ssl_context=ssl_ctx)
