# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
# libsql requires: g++, cmake, and build tools for Rust compilation
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    cmake \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml ./
COPY requirements.txt ./
COPY README.md ./

# Install Python dependencies with uv
RUN uv pip install --system -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY migrations/ ./migrations/

# Create data directory for embedded replicas
RUN mkdir -p /app/data

# Expose port
EXPOSE 8000

# Run the application
# Note: Using uvicorn directly since packages are already installed system-wide
# 'uv run' is primarily for local development with automatic venv management
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
