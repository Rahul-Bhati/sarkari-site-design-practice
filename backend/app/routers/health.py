from fastapi import APIRouter

from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0", "environment": settings.environment}


@router.get("/health/deep")
async def health_deep():
    """Health check that actually touches the database. Used by uptime monitors."""
    checks: dict[str, str] = {}

    try:
        from app.database import db

        db().table("sources").select("id").limit(1).execute()
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"

    checks["anthropic_key"] = "set" if settings.anthropic_api_key else "missing"
    status = "ok" if all(v == "ok" or v == "set" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
