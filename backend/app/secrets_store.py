"""Encrypt small secrets (API keys saved from the UI) before they reach the database.

Fernet (AES-128-CBC + HMAC-SHA256, from the `cryptography` package) with a key derived from a master secret:
`SECRET_KEY` if set, otherwise a random secret generated once and kept in STORAGE_DIR/secret.key (mode 0600).
Rotating the master secret makes stored keys unreadable; the UI then reports "key must be re-entered".
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    s = get_settings()
    master = s.secret_key
    if not master:
        path = s.storage_dir / "secret.key"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            master = path.read_text().strip()
        else:
            master = secrets.token_urlsafe(48)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(master)
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(master.encode()).digest()))


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str | None) -> str | None:
    """Return the plaintext, or None if there is nothing stored or it cannot be decrypted."""
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def hint(plain: str | None) -> str | None:
    """A safe display form of a key: only the last four characters."""
    if not plain:
        return None
    return "…" + plain[-4:] if len(plain) > 8 else "…"
