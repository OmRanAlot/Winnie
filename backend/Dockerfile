# Production image for the Winnie FastAPI service.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Install dependencies separately so source-only changes reuse this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY data ./data

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/recordings \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

# Cloud Run provides PORT; 8080 is useful for local container runs.
CMD ["sh", "-c", "exec fastapi run app/main.py --host 0.0.0.0 --port ${PORT:-8080}"]
