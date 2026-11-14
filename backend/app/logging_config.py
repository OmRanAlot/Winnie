"""Logging setup and the per-request access log.

setup_logging() is called once from app/main.py. RequestLogMiddleware logs every request as
"METHOD /path -> status (ms)" with a short request id, and logs unhandled exceptions with a
traceback, so a 500 always leaves a line explaining itself. Every module logs through
logging.getLogger(__name__), so each line is tagged with the file it came from.
"""

import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
SLOW_REQUEST_MS = 5_000
REQUEST_ID_CHARS = 8

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO") -> None:
    """Send every app log line to stderr. force=True so it wins over uvicorn's reloader setup."""
    logging.basicConfig(level=level.upper(), format=LOG_FORMAT, force=True)
    # Keep third-party chatter (HTTP client internals) out unless debugging.
    for noisy in ("httpx", "httpcore", "google_genai", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = uuid4().hex[:REQUEST_ID_CHARS]
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "[%s] %s %s -> UNHANDLED ERROR (%.0f ms)",
                request_id, request.method, request.url.path, elapsed_ms,
            )
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        if response.status_code >= 500:
            level = logging.ERROR
        elif response.status_code >= 400 or elapsed_ms > SLOW_REQUEST_MS:
            level = logging.WARNING
        else:
            level = logging.INFO
        logger.log(
            level, "[%s] %s %s -> %d (%.0f ms)",
            request_id, request.method, request.url.path, response.status_code, elapsed_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response
