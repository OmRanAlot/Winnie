"""Backend entry point: builds the FastAPI app and registers every router.

Run from backend/:  uv run fastapi dev app/main.py
Interactive API docs: http://localhost:8000/docs

To add an endpoint group, create routes/<feature>.py and include its router below.
What is planned but not built lives in the docstrings of app/__init__.py and routes/__init__.py.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.health import router as health_router
from app.routes.recordings import router as recordings_router
from app.settings import Settings

settings = Settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(recordings_router)
