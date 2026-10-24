"""Application entry point. Run: python -m uvicorn receptionist.main:app."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import model_registry  # noqa: F401 -- register every mapped table
from .migrations import SCHEMA_VERSION
from .api import router as core_router
from .core_policy import router as core_policy_router
from .bookings_ext import router as bookings_ext_router
from .provider_control import router as provider_control_router
from .provider_control import dependency_readiness
from .core_runtime import run_core_jobs, drain_tasks
from .access_controls import AccessControlMiddleware
from .sms_bridge import router as sms_bridge_router
from .calendar_bridge import router as calendar_bridge_router
from .routing import router as routing_router
from .billing import router as billing_router
from .privacy_controls import router as privacy_controls_router
from .ops_controls import router as ops_controls_router, run_control_jobs
from .messaging_controls import router as messaging_controls_router, run_messaging_control_jobs
from .config import settings
from .db import Base, SessionLocal, engine, validate_schema
from .media_api import router as media_router
from .operations import router as ops_router, run_once
from .operations_extensions import router as extensions_router
from .operations_outreach import router as outreach_router
from .operations_uat import router as uat_router
from .payment_policy import router as payment_policy_router
from .partners import router as partner_router, run_partner_jobs
from .seed import seed_demo
from .voice import router as voice_router
from .telemetry import configure_logging, record_http, safe_error_fields, router as telemetry_router

log = logging.getLogger("receptionist")
configure_logging()


async def worker_loop(stop=None):
    stop = stop or asyncio.Event()
    while not stop.is_set():
        try:
            await run_once()
            await run_partner_jobs(SessionLocal)
            with SessionLocal() as db:
                run_control_jobs(db)
                db.commit()
            await run_messaging_control_jobs(SessionLocal)
            with SessionLocal() as db:
                await run_core_jobs(db)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("worker_iteration_failed", extra=safe_error_fields(exc))
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()
    if settings.environment.lower() not in {"production", "prod"}:
        Base.metadata.create_all(engine)
    else:
        verify_production_schema()
    if settings.demo_mode:
        with SessionLocal() as db:
            seed_demo(db)
    stop = asyncio.Event()
    task = asyncio.create_task(worker_loop(stop)) if os.getenv("RUN_WORKER", "false").lower() == "true" else None
    try:
        yield
    finally:
        if task:
            stop.set()
            await drain_tasks({task})


def verify_production_schema():
    with engine.connect() as connection:
        versions = connection.execute(text("SELECT version FROM schema_version")).scalars().all()
        if versions != [SCHEMA_VERSION]:
            raise RuntimeError("Run the supported database migration before starting this version")
        validate_schema(connection)


app = FastAPI(title="Hamava Reception", version="0.2.0", lifespan=lifespan,
              description="Tenant-scoped Persian reception, transactional scheduling and explicit integration states.")
app.add_middleware(AccessControlMiddleware, session_factory=SessionLocal)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key", "X-Action-Reason"],
    expose_headers=["X-Request-ID", "Deprecation", "Sunset", "Link"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    candidate = request.headers.get("X-Request-ID", "")
    correlation = candidate if re.fullmatch(r"[a-zA-Z0-9_-]{8,100}", candidate) else str(uuid4())
    size = request.headers.get("content-length", "0")
    if not size.isdigit() or int(size) > 5_100_000:
        return JSONResponse({"detail": {"code": "REQUEST_TOO_LARGE", "message": "درخواست بزرگ است."}}, status_code=413)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        log.error("request_failed", extra={"request_id": correlation, **safe_error_fields(exc)})
        response = JSONResponse({"detail": {"code": "INTERNAL_ERROR", "message": "درخواست انجام نشد. لطفاً دوباره تلاش کنید یا از پذیرش کمک بگیرید.", "request_id": correlation}}, status_code=500)
    elapsed = time.perf_counter() - start
    route = getattr(request.scope.get("route"), "path", "unmatched")
    record_http(route, request.method, response.status_code, elapsed)
    response.headers.update({"X-Request-ID": correlation, "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
        "Permissions-Policy": "camera=(), microphone=(self), geolocation=()",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' https: wss: ws://localhost:* ws://127.0.0.1:*; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        "Server-Timing": f"app;dur={(time.perf_counter() - start)*1000:.1f}"})
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    if settings.environment.lower() in {"production", "prod"}:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/health")
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "version": "0.2.0", "mode": "demo" if settings.demo_mode else "configured", "database": "reachable"}
    except Exception:
        return JSONResponse({"status": "degraded", "database": "unavailable"}, status_code=503)


@app.get("/api/v1/client-info")
def client_info():
    """Public compatibility handshake; never exposes accounts, provider settings or secrets."""
    return {"product": "hamava", "api_version": 1, "app_version": "0.2.0",
            "mode": "demo" if settings.demo_mode else "configured",
            "demo_mode": settings.demo_mode, "native_clients": True}


@app.get("/ready")
def readiness():
    """Deployment signal with no tenant identifiers or patient information."""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            dependencies = dependency_readiness(db)
        body = {"status": "ready" if dependencies["ready"] else "degraded",
                "database": "reachable", "dependencies_ready": dependencies["ready"]}
        return JSONResponse(body, status_code=200 if dependencies["ready"] else 503)
    except Exception:
        return JSONResponse({"status": "degraded", "database": "unavailable", "dependencies_ready": False}, status_code=503)


app.include_router(core_router)
app.include_router(core_policy_router)
app.include_router(bookings_ext_router)
app.include_router(provider_control_router)
app.include_router(calendar_bridge_router)
app.include_router(routing_router)
app.include_router(billing_router)
app.include_router(privacy_controls_router)
app.include_router(ops_controls_router)
app.include_router(messaging_controls_router)
app.include_router(sms_bridge_router)
app.include_router(voice_router)
app.include_router(ops_router)
app.include_router(extensions_router)
app.include_router(outreach_router)
app.include_router(uat_router)
app.include_router(payment_policy_router)
app.include_router(media_router)
app.include_router(partner_router)
app.include_router(telemetry_router)


class SPAFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        from starlette.exceptions import HTTPException
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404 and "." not in Path(path).name and not path.startswith(("api/", "health")):
                return await super().get_response("index.html", scope)
            raise


frontend = Path(os.getenv("FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist")).resolve()
if frontend.is_dir():
    app.mount("/", SPAFiles(directory=str(frontend), html=True), name="frontend")

