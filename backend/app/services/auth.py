"""Admin authentication.

Two ways in:
  1. `X-Admin-Key: <ADMIN_API_KEY>` — for the scheduler, cron, and CI.
  2. `Authorization: Bearer <supabase access token>` — for humans, checked
     against the `admin_users` table.

Both are rejected outright when ADMIN_API_KEY is unset in production, so a
misconfigured deploy fails closed rather than open.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Header, HTTPException, status

from app.config import settings
from app.database import db

log = logging.getLogger(__name__)


class AdminIdentity:
    def __init__(self, kind: str, user_id: str | None = None, email: str | None = None):
        self.kind = kind  # "service" | "user"
        self.user_id = user_id
        self.email = email


def _unauthorized(detail: str = "Admin credentials required") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def require_admin(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    authorization: str | None = Header(default=None),
) -> AdminIdentity:
    if x_admin_key:
        if not settings.admin_api_key:
            raise _unauthorized("ADMIN_API_KEY is not configured on the server")
        if not hmac.compare_digest(x_admin_key, settings.admin_api_key):
            raise _unauthorized("Invalid admin key")
        return AdminIdentity("service")

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        user = _verify_supabase_user(token)
        if user is None:
            raise _unauthorized("Invalid or expired session")
        if not _is_admin(user["id"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Account is not an admin"
            )
        return AdminIdentity("user", user_id=user["id"], email=user.get("email"))

    raise _unauthorized()


def _verify_supabase_user(token: str) -> dict | None:
    """Ask Supabase Auth who this token belongs to. Never trusts the JWT locally."""
    try:
        res = db().auth.get_user(token)
        user = getattr(res, "user", None)
        if user is None:
            return None
        return {"id": str(user.id), "email": getattr(user, "email", None)}
    except Exception as exc:
        log.info("token verification failed: %s", exc)
        return None


def _is_admin(user_id: str) -> bool:
    res = db().table("admin_users").select("user_id").eq("user_id", user_id).limit(1).execute()
    return bool(res.data)


async def current_user(authorization: str | None = Header(default=None)) -> dict:
    """Authenticated (not necessarily admin) user, for bookmarks and dashboard."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("Sign in required")
    user = _verify_supabase_user(authorization.split(" ", 1)[1].strip())
    if user is None:
        raise _unauthorized("Invalid or expired session")
    return user
