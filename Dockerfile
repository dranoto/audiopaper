# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

RUN apt-get update && apt-get install -y ffmpeg

# Create necessary directories
RUN mkdir -p /app/uploads /app/generated_audio /app/static/figures /app/instance

# Copy the dependencies file to the working directory
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code to the working directory
COPY . .

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Run the command to start the application using Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--timeout", "300", "--log-level", "info", "--access-logfile", "-", "--error-logfile", "-", "--capture-output", "app:app"]
