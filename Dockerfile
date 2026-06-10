# Dockerfile for OBD-Cortex MobileApp Service
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

EXPOSE 8000

# Start Uvicorn
CMD ["uvicorn", "src.main_api:app", "--host", "0.0.0.0", "--port", "8000"]
