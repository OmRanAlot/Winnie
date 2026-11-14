# FastAPI application entrypoint.
#
# TODO:
#   - Create the FastAPI app (title "Winnie").
#   - Register routers from app.api.routes (health, members, roles, tasks, ingestion,
#     notifications, email, webhooks).
#   - CORS for the frontend origin (settings.FRONTEND_ORIGIN).
#   - Lifespan: open DB engine, start app.workers.scheduler, shut both down cleanly.
#   - Global error handler returning the API envelope from app.schemas.common.
#
# Dev server: `uv run fastapi dev app/main.py`
