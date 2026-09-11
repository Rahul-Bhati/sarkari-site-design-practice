import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import admin, bookmarks, entries, health, subscribe, webhooks
from app.services import scheduler

logging.basicConfig(
    level=logging.INFO if not settings.is_production else logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.1,
        send_default_pii=False,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    log.info("SarkariSaar API started (%s)", settings.environment)
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(
    title="SarkariSaar API",
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Key"],
)


@app.exception_handler(httpx.ConnectError)
@app.exception_handler(httpx.ConnectTimeout)
async def upstream_unreachable(request: Request, exc: Exception):
    """Supabase (or another upstream) could not be reached at all.

    Worth separating from a 500: the app is fine, its database is not, and the
    fix is operational rather than a code change. A free-tier Supabase project
    pauses itself after a week of inactivity and its DNS record goes with it,
    which surfaces here as a bare `[Errno 8] nodename nor servname provided` —
    so say what that actually means instead of leaking a stack trace.
    """
    log.error("upstream unreachable on %s: %s", request.url.path, exc)
    detail = "Upstream service unavailable"
    if not settings.is_production:
        detail = (
            f"Could not reach the database ({exc}). Check that SUPABASE_URL is "
            "right and that the Supabase project is not paused or deleted."
        )
    return JSONResponse(status_code=503, content={"detail": detail})


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.error("unhandled error on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error" if settings.is_production else str(exc)},
    )


app.include_router(health.router)
app.include_router(entries.router)
app.include_router(subscribe.router)
app.include_router(bookmarks.router)
app.include_router(webhooks.router)
app.include_router(admin.router)


@app.get("/", include_in_schema=False)
async def root():
    return {"service": "SarkariSaar API", "version": "0.1.0", "docs": "/docs"}
