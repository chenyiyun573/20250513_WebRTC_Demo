# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
# This includes server.py, client.js, html files, and the certs directory
COPY . .

# Make port 8080 available to the world outside this container for HTTPS
EXPOSE 8080

# Define environment variable (optional, for clarity or if needed by app)
ENV NAME WebRTC Demo Server

# Command to run the application
CMD ["python", "server.py"]