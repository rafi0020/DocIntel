"""FastAPI application entry point.

    uvicorn app.main:app --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .api import auth as auth_api
from .api import documents, export, invoices, misc
from .api import settings as settings_api
from .auth import ensure_demo_users, get_principal
from .config import get_settings
from .db import init_db, session_scope
from .security import SecurityHeaders

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with session_scope() as session:
        ensure_demo_users(session)
    yield


settings = get_settings()
app = FastAPI(
    title="DocIntel Document Intelligence API",
    version="2.0.0",
    description="Upload invoices, receipts, scans and spreadsheets; get validated, searchable structured data.",
    lifespan=lifespan,
)
app.add_middleware(SecurityHeaders)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,  # the UI authenticates with an HttpOnly session cookie
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
)

signed_in = [Depends(get_principal)]
app.include_router(documents.router, dependencies=signed_in)
app.include_router(invoices.router, dependencies=signed_in)
app.include_router(misc.router, dependencies=signed_in)
app.include_router(export.router, dependencies=signed_in)
app.include_router(settings_api.router, dependencies=signed_in)
app.include_router(auth_api.router)   # per-endpoint role checks
app.include_router(auth_api.public)   # sign-in / sign-up
app.include_router(misc.public)


@app.get("/", include_in_schema=False)
def root():
    return {"name": "DocIntel API", "docs": "/docs", "health": "/api/health"}
