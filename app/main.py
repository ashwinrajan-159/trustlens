"""FastAPI application entrypoint: lifespan, middleware, exception handlers, routes."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.config import settings
from app.core.exceptions import TrustLensError
from app.core.logging import configure_logging, correlation_id_ctx, get_logger
from app.core.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware

configure_logging(debug=settings.debug, json_logs=settings.is_production)
log = get_logger("app")

CORRELATION_HEADER = "X-Correlation-ID"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("app.startup", environment=settings.environment)
    yield
    log.info("app.shutdown")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Explainable banking fraud detection & underwriting-intelligence platform.",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# Reject oversized bodies before they are routed.
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics at /metrics (#18).
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    cid = request.headers.get(CORRELATION_HEADER) or uuid.uuid4().hex
    token = correlation_id_ctx.set(cid)
    try:
        response = await call_next(request)
    finally:
        correlation_id_ctx.reset(token)
    response.headers[CORRELATION_HEADER] = cid
    return response


@app.exception_handler(TrustLensError)
async def trustlens_error_handler(_request: Request, exc: TrustLensError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    # Never leak internals; the correlation id ties the response to the structured log.
    log.error("unhandled_exception", error=str(exc), exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "An unexpected error occurred"}},
    )


app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["root"])
async def root() -> dict:
    return {"app": settings.app_name, "version": "1.0.0", "docs": "/docs"}
