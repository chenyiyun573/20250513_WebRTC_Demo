FROM python:3.9-slim

WORKDIR /app

# Install system dependencies for aiortc (libopus, libvpx)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsrtp2-dev \
    libopus0 \
    libvpx-dev \
    && rm -rf /var/lib/apt/lists/*


# Copy requirements first to use Docker cache for deps
COPY requirements.txt requirements.txt

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app code
COPY . .

# Expose ports
EXPOSE 8080/tcp
EXPOSE 50000-50050/udp

CMD ["python", "server.py"]
