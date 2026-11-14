"""GET /api/health: liveness check used by the dashboard header and (later) deploys."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Report process health."""
    return {"status": "ok", "service": "winnie-api"}
