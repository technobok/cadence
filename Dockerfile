# Cadence - Self-hosted task tracker
# Multi-stage build for minimal image size

FROM python:3.14-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project files needed for install
COPY pyproject.toml ./
COPY src/ ./src/

# Create virtual environment and install dependencies
RUN uv venv /app/.venv && \
    . /app/.venv/bin/activate && \
    uv pip install .

# Production image
FROM python:3.14-slim

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash cadence

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY --chown=cadence:cadence src/ ./src/
COPY --chown=cadence:cadence worker/ ./worker/
COPY --chown=cadence:cadence database/ ./database/
COPY --chown=cadence:cadence wsgi.py ./
COPY --chown=cadence:cadence pyproject.toml ./

# Create instance directory
RUN mkdir -p /app/instance && chown cadence:cadence /app/instance

# Set environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

USER cadence

EXPOSE 5000

# Default command runs the Flask app
CMD ["python", "wsgi.py"]
