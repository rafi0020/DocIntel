"""Accounts, sessions and role checks.

Design choices (see docs/ARCHITECTURE.md, "Accounts and security"):

* Passwords are hashed with scrypt from the standard library (memory-hard, no extra dependency)
  and compared in constant time. Unknown e-mails still pay the hashing cost so response time
  does not reveal which accounts exist.
* A login creates a *server-side* session: a random 256-bit token is handed to the browser in an
  HttpOnly, SameSite=Lax cookie and only its SHA-256 hash is stored. Logging out or deactivating
  a user revokes access immediately, which a self-contained JWT could not do.
* State-changing requests that carry the cookie must come from an allowed Origin (CSRF defence in
  depth on top of SameSite).
* Roles: viewer (read), reviewer (upload, correct, approve, reprocess), admin (everything,
  plus users and the audit log). The optional `API_KEY` acts as a service account with the
  reviewer role for scripts.
* Repeated failures lock the account for a few minutes; every sign-in, upload, correction and
  admin action is written to the audit log.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_session
from .models import AuditLog, AuthSession, User

COOKIE = "docintel_session"
ROLES = ("viewer", "reviewer", "admin")
RANK = {r: i for i, r in enumerate(ROLES)}
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


# --------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, dk = stored.split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password("not-a-real-password")


def password_problem(password: str, email: str = "") -> str | None:
    """Return a human-readable reason the password is unacceptable, or None."""
    if len(password) < 10:
        return "Use at least 10 characters."
    if len(password) > 128:
        return "Use at most 128 characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Include at least one letter and one number."
    local = email.split("@")[0].lower()
    if local and len(local) >= 4 and local in password.lower():
        return "Do not include your e-mail name in the password."
    return None


def normalize_email(email: str) -> str:
    e = (email or "").strip().lower()
    if len(e) > 254 or not EMAIL_RE.match(e):
        raise HTTPException(422, "Enter a valid e-mail address.")
    return e


# --------------------------------------------------------------------- principal
@dataclass
class Principal:
    id: uuid.UUID | None
    email: str
    name: str
    role: str
    via: str  # "session" | "api_key"

    def can(self, role: str) -> bool:
        return RANK[self.role] >= RANK[role]


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def create_session(session: Session, user: User, request: Request, remember: bool) -> tuple[str, AuthSession]:
    s = get_settings()
    token = secrets.token_urlsafe(32)
    ttl = timedelta(days=s.remember_days) if remember else timedelta(hours=s.session_hours)
    row = AuthSession(user_id=user.id, token_hash=_hash_token(token), user_agent=(request.headers.get("user-agent") or "")[:300],
                      ip=client_ip(request), expires_at=_now() + ttl)
    session.add(row)
    session.execute(delete(AuthSession).where(AuthSession.expires_at < _now()))  # opportunistic clean-up
    return token, row


def set_cookie(response: Response, token: str, remember: bool) -> None:
    s = get_settings()
    max_age = s.remember_days * 86400 if remember else s.session_hours * 3600
    response.set_cookie(COOKIE, token, max_age=max_age, httponly=True, samesite="lax", secure=s.cookie_secure, path="/")


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def _check_origin(request: Request) -> None:
    """Cookie-authenticated writes must originate from an allowed origin."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    origin = request.headers.get("origin")
    if origin is None:
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Cross-site request blocked")
        return
    if origin not in get_settings().cors_origin_list:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Request origin is not allowed")


def get_principal(request: Request, session: Session = Depends(get_session)) -> Principal:
    s = get_settings()
    # 1) service account via API key
    key = request.headers.get("x-api-key")
    if key and s.api_key and hmac.compare_digest(key.encode(), s.api_key.encode()):
        return Principal(None, "service@api-key", "API key", "reviewer", "api_key")
    # 2) browser session cookie, or the same token as a Bearer header for API clients
    token = request.cookies.get(COOKIE)
    bearer = False
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token, bearer = auth[7:].strip(), True
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required", headers={"WWW-Authenticate": "Bearer"})
    row = session.scalars(select(AuthSession).where(AuthSession.token_hash == _hash_token(token))).first()
    if row is None or row.expires_at < _now() or not row.user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please sign in again.")
    if not bearer:
        _check_origin(request)
    if (_now() - row.last_seen_at) > timedelta(minutes=5):
        row.last_seen_at = _now()
        session.commit()
    u = row.user
    return Principal(u.id, u.email, u.name, u.role, "session")


def need(role: str):
    """Dependency factory: `principal: Principal = Depends(need("reviewer"))`."""

    def dep(p: Principal = Depends(get_principal)) -> Principal:
        if not p.can(role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role ({p.role}) cannot do this. {role.capitalize()} access is required.")
        return p

    return dep


# --------------------------------------------------------------------- audit
def audit(session: Session, who: Principal | User | None, action: str, target_type: str | None = None, target_id: object = None,
          detail: dict | None = None, request: Request | None = None) -> None:
    uid = getattr(who, "id", None)
    session.add(AuditLog(user_id=uid, user_email=getattr(who, "email", None), user_name=getattr(who, "name", None), action=action,
                         target_type=target_type, target_id=str(target_id) if target_id is not None else None, detail=detail or None,
                         ip=client_ip(request) if request else None))


# --------------------------------------------------------------------- login
def authenticate(session: Session, email: str, password: str) -> User:
    """Verify credentials, applying the lock-out policy. Raises 401/429 with generic messages."""
    s = get_settings()
    user = session.scalars(select(User).where(User.email == email)).first()
    if user is None:
        verify_password(password, _DUMMY_HASH)  # equalise timing
        raise HTTPException(401, "Invalid e-mail or password.")
    if user.locked_until and user.locked_until > _now():
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
    if not verify_password(password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= s.login_max_attempts:
            user.locked_until = _now() + timedelta(minutes=s.login_lock_minutes)
            user.failed_attempts = 0
        session.commit()
        raise HTTPException(401, "Invalid e-mail or password.")
    if not user.is_active:
        raise HTTPException(403, "This account has been deactivated. Contact an administrator.")
    user.failed_attempts, user.locked_until, user.last_login_at = 0, None, _now()
    return user


def ensure_bootstrap_admin(session: Session) -> None:
    """Create the first administrator from BOOTSTRAP_ADMIN_EMAIL / _PASSWORD when no admin exists."""
    s = get_settings()
    if not (s.bootstrap_admin_email and s.bootstrap_admin_password):
        return
    session.execute(text("SELECT pg_advisory_xact_lock(724002)"))
    if session.scalars(select(User).where(User.role == "admin")).first():
        return
    email = normalize_email(s.bootstrap_admin_email)
    problem = password_problem(s.bootstrap_admin_password, email)
    if problem:
        raise RuntimeError(f"BOOTSTRAP_ADMIN_PASSWORD rejected: {problem}")
    session.add(User(email=email, name="Administrator", role="admin", password_hash=hash_password(s.bootstrap_admin_password)))
    session.commit()


def ensure_demo_users(session: Session) -> None:
    """Create the documented demo accounts if they do not exist (never overwrites a password)."""
    s = get_settings()
    ensure_bootstrap_admin(session)
    if not s.seed_demo_users:
        return
    demo = [
        ("admin@docintel.demo", "Demo Admin", "admin", s.demo_admin_password),
        ("reviewer@docintel.demo", "Demo Reviewer", "reviewer", s.demo_reviewer_password),
        ("viewer@docintel.demo", "Demo Viewer", "viewer", s.demo_viewer_password),
    ]
    # API replicas start together: serialise the seed so two processes cannot insert the same account.
    session.execute(text("SELECT pg_advisory_xact_lock(724002)"))
    for email, name, role, pw in demo:
        if session.scalars(select(User).where(User.email == email)).first() is None:
            session.add(User(email=email, name=name, role=role, password_hash=hash_password(pw)))
    session.commit()
