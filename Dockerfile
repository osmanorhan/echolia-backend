# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml ./
COPY requirements.txt ./

# Install Python dependencies with uv
RUN uv pip install --system -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY migrations/ ./migrations/

# Create data directory for embedded replicas
RUN mkdir -p /app/data

# Expose port
EXPOSE 8000

# Run the application with uv
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
