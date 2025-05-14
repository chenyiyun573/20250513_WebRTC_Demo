// client.js
let localStream;
let pc;
let ws;
let clientRole; // 'publisher' or 'subscriber'

const configuration = {
    iceServers: [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' }
        // For production, add TURN servers
    ]
};

function getWebSocketURL() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.hostname}:${window.location.port}/ws`;
}

async function init(role) {
    clientRole = role;
    document.getElementById('status').textContent = `Initializing as ${clientRole}...`;

    if (clientRole === 'publisher') {
        document.getElementById('startButton').onclick = startPublisher;
        document.getElementById('stopButton').onclick = stopStream;
    } else if (clientRole === 'subscriber') {
        document.getElementById('startButton').onclick = startSubscriber;
        document.getElementById('stopButton').onclick = stopStream;
    }
    document.getElementById('stopButton').disabled = true;
}

async function connectWebSocket() {
    return new Promise((resolve, reject) => {
        if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
            console.log("WebSocket already open or connecting.");
            resolve(); // Potentially already resolved or will be by existing connection
            return;
        }

        ws = new WebSocket(getWebSocketURL());

        ws.onopen = () => {
            console.log('WebSocket connection established');
            document.getElementById('status').textContent = 'WebSocket connected.';
            ws.send(JSON.stringify({ type: 'role', role: clientRole }));
            resolve();
        };

        ws.onmessage = async (message) => {
            const data = JSON.parse(message.data);
            console.log('Received message from server:', data);
            document.getElementById('status').textContent = `Received: ${data.type}`;

            if (!pc && (data.type === 'offer' || data.type === 'answer' || data.type === 'candidate')) {
                // Ensure PC is created if server sends offer/answer first
                console.log("PC not created, creating one due to incoming message.");
                await createPeerConnection(); // Create PC if it doesn't exist
            }


            if (data.type === 'offer') {
                if (clientRole === 'subscriber') {
                    await pc.setRemoteDescription(new RTCSessionDescription(data));
                    const answer = await pc.createAnswer();
                    await pc.setLocalDescription(answer);
                    ws.send(JSON.stringify({ type: 'answer', sdp: pc.localDescription.sdp }));
                    console.log('Sent answer to server');
                    document.getElementById('status').textContent = 'Answer sent.';
                }
            } else if (data.type === 'answer') {
                 if (clientRole === 'publisher') {
                    await pc.setRemoteDescription(new RTCSessionDescription(data));
                    console.log('Remote description (answer) set');
                    document.getElementById('status').textContent = 'Stream negotiation complete.';
                }
            } else if (data.type === 'candidate') {
                try {
                    const candidateData = (typeof data.candidate === 'string') ? JSON.parse(data.candidate) : data.candidate;
                    if (candidateData && pc.signalingState !== 'closed') { // Check if pc is still valid
                        await pc.addIceCandidate(new RTCIceCandidate(candidateData));
                        console.log('Added ICE candidate from server');
                    } else {
                        console.warn("Could not add ICE candidate, PC might be closed or candidate data invalid.");
                    }
                } catch (e) {
                    console.error('Error adding received ICE candidate', e);
                }
            } else if (data.type === 'error') {
                console.error('Server error:', data.message);
                document.getElementById('status').textContent = `Server error: ${data.message}`;
            }
        };

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            document.getElementById('status').textContent = 'WebSocket error.';
            reject(error);
        };

        ws.onclose = () => {
            console.log('WebSocket connection closed');
            document.getElementById('status').textContent = 'WebSocket closed.';
            // Don't nullify pc here directly, let stopStream handle it if called
            // Or manage pc lifecycle more carefully based on connection state.
            if(pc && pc.signalingState !== "closed"){
                 // pc.close(); // This might be too aggressive, let stopStream handle it
            }
            document.getElementById('startButton').disabled = false;
            document.getElementById('stopButton').disabled = true;
        };
    });
}


async function createPeerConnection() {
    if (pc && pc.signalingState !== 'closed') {
        console.log("PeerConnection already exists and is not closed.");
        return;
    }
    console.log('Creating PeerConnection with configuration:', configuration);
    pc = new RTCPeerConnection(configuration);

    pc.onicecandidate = (event) => {
        if (event.candidate && ws && ws.readyState === WebSocket.OPEN) {
            console.log('Sending ICE candidate to server:', event.candidate);
            ws.send(JSON.stringify({
                type: 'candidate',
                candidate: event.candidate.toJSON()
            }));
        }
    };

    pc.oniceconnectionstatechange = () => {
        if (!pc) return; // Guard against pc being nullified
        console.log(`ICE connection state: ${pc.iceConnectionState}`);
        document.getElementById('status').textContent = `ICE State: ${pc.iceConnectionState}`;
        if (pc.iceConnectionState === 'connected' && clientRole === 'subscriber') {
             document.getElementById('status').textContent = 'Stream connected!';
        }
        if (pc.iceConnectionState === 'failed' || pc.iceConnectionState === 'disconnected' || pc.iceConnectionState === 'closed') {
            console.warn('ICE connection problematic or closed:', pc.iceConnectionState);
            // Consider calling stopStream() or a more graceful cleanup here if needed
            // For example, if state is 'failed', you might want to attempt a restart or notify the user.
            if (pc.iceConnectionState === 'closed') {
                 document.getElementById('startButton').disabled = false;
                 document.getElementById('stopButton').disabled = true;
            }
        }
    };

    pc.ontrack = (event) => {
        console.log('Track received:', event.track, 'Streams:', event.streams);
        document.getElementById('status').textContent = `Track received: ${event.track.kind}`;
        const remoteVideo = document.getElementById('remoteVideo');
        if (remoteVideo) {
            if (!remoteVideo.srcObject || remoteVideo.srcObject !== event.streams[0]) { // Check if stream is already set
                remoteVideo.srcObject = event.streams[0]; // Use the stream directly
                 remoteVideo.play().catch(e => console.error("Error playing remote video:", e));
            }
        } else if (clientRole === 'subscriber') { // Only warn if it's a subscriber expecting video
            console.warn("Remote video element not found for track display.");
        }
    };
}

// --- Publisher specific ---
async function startPublisher() {
    document.getElementById('startButton').disabled = true;
    document.getElementById('stopButton').disabled = false;
    document.getElementById('status').textContent = "Starting publisher...";

    try {
        await connectWebSocket();
        await createPeerConnection();

        console.log("Requesting local media...");
        localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        const localVideo = document.getElementById('localVideo');
        if (localVideo) {
            localVideo.srcObject = localStream;
        } else {
            console.warn("Local video element not found.");
        }
        document.getElementById('status').textContent = "Media obtained.";

        localStream.getTracks().forEach(track => {
            if (pc && pc.signalingState !== 'closed') {
                console.log('Adding local track to PC:', track.kind);
                pc.addTrack(track, localStream);
            }
        });

        if (pc && pc.signalingState !== 'closed') {
            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);
            console.log('Sending offer to server:', offer.sdp);
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'offer', sdp: offer.sdp }));
                document.getElementById('status').textContent = "Offer sent. Waiting for answer...";
            } else {
                 document.getElementById('status').textContent = "WebSocket not open to send offer.";
                 console.error("WebSocket not open to send offer.");
            }
        }

    } catch (e) {
        console.error('Error starting publisher:', e);
        alert(`Error starting stream: ${e.name} - ${e.message}. Ensure HTTPS and permissions.`);
        document.getElementById('status').textContent = `Error: ${e.message}`;
        stopStream();
    }
}

// --- Subscriber specific ---
async function startSubscriber() {
    document.getElementById('startButton').disabled = true;
    document.getElementById('stopButton').disabled = false;
    document.getElementById('status').textContent = "Starting subscriber...";

    try {
        await connectWebSocket();
        await createPeerConnection(); // Create PC, server will send offer
        console.log("Subscriber waiting for offer from server...");
        document.getElementById('status').textContent = "Waiting for stream offer...";

    } catch (e) {
        console.error('Error starting subscriber:', e);
        document.getElementById('status').textContent = `Error: ${e.message}`;
        stopStream();
    }
}

function stopStream() {
    document.getElementById('status').textContent = "Stopping stream...";
    if (localStream) {
        localStream.getTracks().forEach(track => track.stop());
        localStream = null;
        const localVideo = document.getElementById('localVideo');
        if (localVideo) localVideo.srcObject = null;
        console.log("Local stream stopped.");
    }

    if (pc) {
        if (pc.signalingState !== 'closed') {
            pc.close();
        }
        pc = null; // Ensure pc is reset
        console.log("Peer connection closed.");
    }

    // Only close WebSocket if it's open. send hangup message before closing.
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'hangup' }));
        ws.close();
        console.log("WebSocket hangup sent and closing.");
    } else if (ws && ws.readyState === WebSocket.CONNECTING) {
        // If it's still connecting, just set onclose to null to prevent further actions
        // and then close it. Or simply close it.
        ws.onclose = null; // Prevent onclose handler from re-triggering logic
        ws.close();
        console.log("WebSocket was connecting, now closing.");
    }


    const remoteVideo = document.getElementById('remoteVideo');
    if (remoteVideo) remoteVideo.srcObject = null;

    document.getElementById('startButton').disabled = false;
    document.getElementById('stopButton').disabled = true;
    document.getElementById('status').textContent = "Stream stopped.";
    console.log("Stream stopped and resources cleaned up.");
}