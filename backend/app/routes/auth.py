"""Current verified user's private profile; permits invited members to finish password setup."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import Principal, get_principal

router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.get("/me")
def current_user(principal: Annotated[Principal, Depends(get_principal)]):
    return {"success": True, "data": principal.profile, "error": None, "meta": {}}
