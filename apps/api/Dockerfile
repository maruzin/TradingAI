# TradingAI backend image — used by Fly.io / Railway / any container host.
# Build:  fly deploy
# Run:    fly logs

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# System deps for asyncpg + ccxt + pandas-ta (numpy/scipy)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv for fast deterministic installs
RUN pip install uv==0.5.* && uv --version

WORKDIR /app

# Copy dep manifests first for better layer caching
COPY pyproject.toml ./
COPY uv.lock* ./

# Install runtime deps (no dev). Cache the venv layer.
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

# Copy the rest of the app
COPY app ./app

ENV PORT=8080 \
    HOST=0.0.0.0

EXPOSE 8080

# Health probe target
HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:${PORT}/healthz || exit 1

# Start the API. Use a single worker — workers run as a separate process group.
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
