from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .api import auth, documents, findings, invoices, search_api, system
from .config import get_settings
from .database import SessionLocal, init_db, seed_db
from .storage import get_storage
from .worker import start_background_worker

settings = get_settings()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_db()
    try:
        get_storage()
    except Exception as exc:
        logger.warning("storage initialization warning: %s", exc)
    worker = None
    thread = None
    if settings.auto_worker:
        worker, thread = start_background_worker()
        logger.info("inline background worker started")
    yield
    if worker:
        worker.stop()
    if thread:
        thread.join(timeout=10)


app = FastAPI(
    title="DocIntel API",
    version="1.0.0",
    description=(
        "AI-powered document intelligence: OCR, LLM extraction, validation, "
        "reconciliation, review, and hybrid search."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "If-Match", "X-Requested-With"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "type": "about:blank",
            "title": "Internal Server Error",
            "status": 500,
            "detail": "An unexpected error occurred",
        },
    )


@app.get("/health/live", tags=["system"])
def root_health_live() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", tags=["system"])
def root_health_ready() -> dict:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    finally:
        db.close()
    return {"status": "ok"}


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(documents.router, prefix=settings.api_prefix)
app.include_router(findings.router, prefix=settings.api_prefix)
app.include_router(invoices.router, prefix=settings.api_prefix)
app.include_router(search_api.router, prefix=settings.api_prefix)
app.include_router(system.router, prefix=settings.api_prefix)


@app.get("/", tags=["system"])
def root() -> dict:
    return {
        "app": settings.app_name,
        "docs": "/docs",
        "health": "/health/ready",
        "api": settings.api_prefix,
    }
