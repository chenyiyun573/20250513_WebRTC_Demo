FROM python:3.11-slim

WORKDIR /app

# Copy app files and certs
COPY relay.py publisher.html viewer.html cert.pem key.pem ./

RUN pip install --no-cache-dir websockets

EXPOSE 8443 8765
CMD ["python", "relay.py"]
