"""Aggregate v1 routers under one APIRouter."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import applications, auth, documents, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(applications.router)
api_router.include_router(documents.router)
