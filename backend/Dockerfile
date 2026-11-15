# Production image for the Winnie FastAPI service.
FROM node:22-bookworm-slim AS photon
WORKDIR /photon
COPY photon/package.json photon/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts
COPY photon/send.mjs ./

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
COPY --from=photon /usr/local/bin/node /usr/local/bin/node
COPY --from=photon /photon /app/photon
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 && node --version
# Only the versioned runtime fixture belongs in the image. Local data may contain
# recordings, credentials, virtual environments, or database state.
COPY data/eboardMembers.json ./data/eboardMembers.json

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/recordings \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

# Cloud Run provides PORT; 8080 is useful for local container runs.
CMD ["sh", "-c", "exec fastapi run app/main.py --host 0.0.0.0 --port ${PORT:-8080}"]
