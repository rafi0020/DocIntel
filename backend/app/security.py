"""Request-level security: upload hygiene and response headers (authentication lives in auth.py)."""
from __future__ import annotations

import re
import unicodedata

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

ALLOWED_EXT = {"pdf", "png", "jpg", "jpeg", "tif", "tiff", "xlsx", "xls", "csv"}


def safe_filename(name: str) -> str:
    """Keep a display-safe filename (no paths, control chars or odd unicode)."""
    name = unicodedata.normalize("NFKC", name or "upload")
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^\w.\- ()\[\]]", "_", name).strip(" .")
    return (name or "upload")[:200]


def extension_ok(name: str) -> bool:
    return "." in name and name.rsplit(".", 1)[-1].lower() in ALLOWED_EXT


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        return resp
