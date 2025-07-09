FROM python:3.11-slim

# runtime deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY relay.py .

# if you use cert.pem/key.pem for TLS, copy them too:
# COPY cert.pem key.pem ./

EXPOSE 8765/tcp
CMD ["python", "relay.py"]
