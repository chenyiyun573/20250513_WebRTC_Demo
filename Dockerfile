FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir websockets==12.*  # or any >=12
EXPOSE 8443 8765
CMD ["python", "relay.py"]
