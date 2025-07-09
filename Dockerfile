# stream-relay/Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY relay.py publisher.html viewer.html cert.pem key.pem ./

# lightweight deps only
RUN pip install --no-cache-dir websockets

EXPOSE 8765 8443          # 8765 = WSS, 8443 = HTTPS for static files
CMD ["python", "relay.py"]
