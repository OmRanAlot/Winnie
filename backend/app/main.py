"""Backend entry point: builds the FastAPI app and registers every router.

Run from backend/:  uv run fastapi dev app/main.py
Interactive API docs: http://localhost:8000/docs

To add an endpoint group, create routes/<feature>.py and include its router below.
What is planned but not built lives in the docstrings of app/__init__.py and routes/__init__.py.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.logging_config import RequestLogMiddleware, setup_logging
from app.routes.health import router as health_router
from app.routes.members import router as members_router
from app.routes.recordings import router as recordings_router
from app.routes.tasks import router as tasks_router
from app.routes.planning import router as planning_router
from app.settings import Settings
# pyrefly: ignore[missing-import]
from app.routes.messages import router as messages_router

settings = Settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(RequestLogMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(recordings_router)
app.include_router(tasks_router)
app.include_router(messages_router)
app.include_router(planning_router)
app.include_router(members_router)
