import asyncio
import json
import logging
import os
import ssl
import uuid

from aiohttp import web
from aiortc import RTCIceCandidate, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay

ROOT = os.path.dirname(__file__)
CERTS_DIR = os.path.join(ROOT, "certs") # Path to SSL certificates

# Global set to keep track of peer connections
pcs = set()
# Global relay to forward tracks from publisher to subscribers
relay = MediaRelay()
# Store the publisher's tracks globally
publisher_tracks = {"audio": None, "video": None}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webrtc_server")

async def serve_html(request, file_name):
    file_path = os.path.join(ROOT, file_name)
    try:
        with open(file_path, "r") as f:
            content = f.read()
        return web.Response(content_type="text/html", text=content)
    except FileNotFoundError:
        logger.error(f"HTML file not found: {file_path}")
        return web.Response(status=404, text="File not found")


async def serve_javascript(request, file_name):
    file_path = os.path.join(ROOT, file_name)
    try:
        with open(file_path, "r") as f:
            content = f.read()
        return web.Response(content_type="application/javascript", text=content)
    except FileNotFoundError:
        logger.error(f"JavaScript file not found: {file_path}")
        return web.Response(status=404, text="File not found")

async def publisher_page(request):
    return await serve_html(request, "publisher.html")

async def viewer_page(request):
    return await serve_html(request, "viewer.html")

async def client_js_route(request): # Renamed to avoid conflict with client_js variable
    return await serve_javascript(request, "client.js")

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    client_id = str(uuid.uuid4())
    logger.info(f"WebSocket client connected: {client_id}")

    pc = RTCPeerConnection()
    pcs.add(pc)
    client_role = None

    @pc.on("icecandidate")
    async def on_icecandidate(candidate):
        if candidate:
            logger.info(f"Sending ICE candidate to {client_id}: {candidate.to_json()}")
            await ws.send_json({
                "type": "candidate",
                "candidate": candidate.to_json()
            })

    @pc.on("track")
    async def on_track(track):
        logger.info(f"Track {track.kind} received from publisher {client_id}")
        if client_role == "publisher":
            if track.kind == "audio":
                # For audio, you might want to relay it differently or just pass it through
                # For simplicity, we'll treat it like video for relaying if needed.
                # publisher_tracks["audio"] = relay.subscribe(track) # Or just store track if server processes it
                publisher_tracks["audio"] = track
            elif track.kind == "video":
                publisher_tracks["video"] = relay.subscribe(track)
            logger.info(f"Publisher {client_id} tracks stored/relayed: Audio - {'Set' if publisher_tracks['audio'] else 'None'}, Video - {'Set' if publisher_tracks['video'] else 'None'}")
        @track.on("ended")
        async def on_ended():
            logger.info(f"Track {track.kind} from {client_id} ended")
            if client_role == "publisher":
                if track.kind == "audio" and publisher_tracks["audio"] == track: # Check if it's the exact track
                    publisher_tracks["audio"] = None
                # For relayed video tracks, comparison might be tricky.
                # The relay.subscribe returns a new track. This needs robust handling.
                # For simplicity, we assume the video track object in publisher_tracks["video"] is what we check.
                # A more robust way might involve checking the original track if the relay allows.
                elif track.kind == "video" and publisher_tracks["video"] is not None: # Simplified check
                     publisher_tracks["video"] = None # Clears the relayed track
                logger.info(f"Publisher {client_id} tracks after ended: Audio - {'Set' if publisher_tracks['audio'] else 'None'}, Video - {'Set' if publisher_tracks['video'] else 'None'}")


    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info(f"PC {client_id} ({client_role}) connection state is {pc.connectionState}")
        if pc.connectionState == "failed" or pc.connectionState == "closed" or pc.connectionState == "disconnected":
            logger.info(f"PC {client_id} ({client_role}) disconnected or failed.")
            await cleanup_client_resources(pc, client_id, client_role, ws)


    async def cleanup_client_resources(peer_connection, c_id, c_role, websocket):
        if peer_connection in pcs:
            logger.info(f"Closing PC for {c_id} ({c_role}).")
            await peer_connection.close()
            pcs.discard(peer_connection)
        
        if c_role == "publisher":
            logger.info(f"Publisher {c_id} disconnected. Clearing global tracks.")
            publisher_tracks["audio"] = None
            publisher_tracks["video"] = None
        
        if not websocket.closed:
            logger.info(f"Closing WebSocket for {c_id}.")
            await websocket.close()
        logger.info(f"Cleaned up resources for client {c_id}.")


    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                logger.debug(f"Received message from {client_id} ({client_role}): {data}")

                if data["type"] == "role":
                    client_role = data["role"]
                    logger.info(f"Client {client_id} assigned role: {client_role}")

                    if client_role == "subscriber":
                        if publisher_tracks["audio"]:
                            logger.info(f"Adding existing audio track to subscriber {client_id}")
                            pc.addTrack(publisher_tracks["audio"])
                        if publisher_tracks["video"]:
                            logger.info(f"Adding existing video track (relayed) to subscriber {client_id}")
                            pc.addTrack(publisher_tracks["video"])
                        else:
                            logger.info(f"No video track available for subscriber {client_id} yet.")
                        
                        offer = await pc.createOffer()
                        await pc.setLocalDescription(offer)
                        await ws.send_json({"type": "offer", "sdp": offer.sdp})

                elif data["type"] == "offer":
                    offer_sdp = RTCSessionDescription(sdp=data["sdp"], type="offer")
                    await pc.setRemoteDescription(offer_sdp)
                    
                    answer_sdp = await pc.createAnswer()
                    await pc.setLocalDescription(answer_sdp)
                    await ws.send_json({
                        "type": "answer",
                        "sdp": pc.localDescription.sdp
                    })

                elif data["type"] == "answer":
                    answer_sdp = RTCSessionDescription(sdp=data["sdp"], type="answer")
                    await pc.setRemoteDescription(answer_sdp)

# server.py - in websocket_handler
# ... modified by troubleshooting 20250513 2140 CT
                elif data["type"] == "candidate":
                    logger.debug(f"Received candidate payload from {client_id}: {data['candidate']}")
                    cand_payload = data["candidate"]  # This IS the object from event.candidate.toJSON()

                    actual_candidate_string = cand_payload.get("candidate") # The "candidate:..." string
                    sdp_mid = cand_payload.get("sdpMid")
                    sdp_m_line_index = cand_payload.get("sdpMLineIndex")

                    if actual_candidate_string:
                        # Create an RTCIceCandidate descriptor.
                        # Set its .candidate attribute to the full string, plus sdpMid and sdpMLineIndex.
                        # aiortc's pc.addIceCandidate will then parse the .candidate string.
                        ice_candidate_obj_for_aiortc = RTCIceCandidate(
                            sdpMid=sdp_mid,
                            sdpMLineIndex=sdp_m_line_index
                        )
                        ice_candidate_obj_for_aiortc.candidate = actual_candidate_string # Crucial step

                        try:
                            logger.debug(f"Adding ICE candidate for {client_id}: mid={ice_candidate_obj_for_aiortc.sdpMid}, lineIndex={ice_candidate_obj_for_aiortc.sdpMLineIndex}, cand='{ice_candidate_obj_for_aiortc.candidate}'")
                            await pc.addIceCandidate(ice_candidate_obj_for_aiortc)
                            logger.debug(f"Successfully added ICE candidate for {client_id}")
                        except Exception as e_add_ice:
                            logger.error(f"Error in pc.addIceCandidate for {client_id}: {e_add_ice}")
                            logger.error(f"Problematic ICE candidate object: {vars(ice_candidate_obj_for_aiortc)}")
                    else:
                        logger.warning(f"Received candidate message from {client_id} without an actual 'candidate' string in the payload.")
# ...

                elif data["type"] == "hangup":
                    logger.info(f"Client {client_id} ({client_role}) initiated hangup.")
                    await cleanup_client_resources(pc, client_id, client_role, ws)
                    break # Exit message loop

            elif msg.type == web.WSMsgType.ERROR:
                logger.error(f"WebSocket connection for {client_id} closed with exception {ws.exception()}")
                await cleanup_client_resources(pc, client_id, client_role, ws)
                break # Exit message loop
            elif msg.type == web.WSMsgType.CLOSED:
                logger.info(f"WebSocket connection for {client_id} closed by client.")
                await cleanup_client_resources(pc, client_id, client_role, ws)
                break # Exit message loop

    except Exception as e:
        logger.error(f"Error in WebSocket handler for {client_id}: {e}")
        await cleanup_client_resources(pc, client_id, client_role, ws)
    finally:
        logger.info(f"WebSocket client {client_id} ({client_role}) processing finished.")
        # Ensure cleanup if not already done
        if not ws.closed: # If ws isn't closed, it means loop exited for other reasons
             await cleanup_client_resources(pc, client_id, client_role, ws)

    return ws

async def on_shutdown(app_instance):
    coros = [pc.close() for pc in list(pcs)] # list(pcs) to avoid issues if pcs is modified during iteration
    await asyncio.gather(*coros, return_exceptions=True)
    pcs.clear()
    logger.info("All peer connections closed during shutdown.")

app = web.Application()
app.on_shutdown.append(on_shutdown)
app.router.add_get("/", viewer_page)
app.router.add_get("/publisher", publisher_page)
app.router.add_get("/viewer", viewer_page)
app.router.add_get("/client.js", client_js_route) # Use the renamed route
app.router.add_get("/ws", websocket_handler)

if __name__ == "__main__":
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    cert_path = os.path.join(CERTS_DIR, 'server.crt')
    key_path = os.path.join(CERTS_DIR, 'server.key')

    try:
        ssl_context.load_cert_chain(cert_path, key_path)
        logger.info(f"SSL certificates loaded successfully from {CERTS_DIR}.")
        web.run_app(app, host="0.0.0.0", port=8080, ssl_context=ssl_context)
        logger.info("Server started on https://0.0.0.0:8080")
    except FileNotFoundError:
        logger.error(f"SSL certificates (server.crt, server.key) not found in {CERTS_DIR}.")
        logger.error("WebRTC requires HTTPS. Please generate certificates and place them in the 'certs' directory.")
        logger.info("Server will not start without SSL certificates.")
    except ssl.SSLError as e:
        logger.error(f"SSL Error: {e}. Check your certificate and key files in {CERTS_DIR}.")
        logger.info("Server will not start due to SSL error.")
    except Exception as e:
        logger.error(f"Failed to start server: {e}")