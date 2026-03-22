# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY backend/requirements.txt ./backend/

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy the rest of the application code
COPY . .

# Set WORKDIR to the backend folder for running the app
WORKDIR /app/backend

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Run the application with Gunicorn and the Eventlet worker for WebSockets
# Use the shell form to allow environment variable expansion
CMD gunicorn --worker-class eventlet -w 1 -b 0.0.0.0:${PORT:-5000} app:app
