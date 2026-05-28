FROM python:3.12-slim

WORKDIR /app

# Install curl for healthcheck and build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY router.py .
COPY run_autonomous.py .
COPY agents/ ./agents/
COPY core/ ./core/

# Logging directory
RUN mkdir -p /app/logs

# Non-root user
RUN useradd -m -r app && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "router:app", "--host", "0.0.0.0", "--port", "8000"]
