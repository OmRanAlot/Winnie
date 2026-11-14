from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings

settings = Settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["health"])
def health() -> dict[str, str]:
    """Report process health; no provider integrations are connected yet."""
    return {"status": "ok", "service": "winnie-api"}


# TODO:
#   - Move /api/health into app.api.routes.health and register routers from app.api.routes
#     (health, members, roles, tasks, ingestion, notifications, email, webhooks).
#   - Lifespan: open DB engine, start app.workers.scheduler, shut both down cleanly.
#   - Global error handler returning the API envelope from app.schemas.common.
#
# Dev server: `uv run fastapi dev app/main.py`
