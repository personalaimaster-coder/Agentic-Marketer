FROM python:3.11-slim

# Keep the image lean — no dev tools
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# Install deps first (layer-cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY marketing_agent/ ./marketing_agent/
COPY server.py .

# Cloud Run expects the service to listen on $PORT
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port $PORT"]
