# Dockerfile for Akleao Research API and Celery worker
FROM python:3.13-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . && \
    pip install --no-cache-dir celery redis tavily-python pillow pandas openpyxl websockets email-validator

# Copy application code
COPY api/ ./api/
COPY rag/ ./rag/

# Create directories for uploads and data
RUN mkdir -p uploads git_repos

# Expose port for API
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
