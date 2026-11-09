"""Sign-in, sign-up, profile, user administration, audit log and activity feed."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..auth import (
    ROLES,
    Principal,
    audit,
    authenticate,
    clear_cookie,
    create_session,
    get_principal,
    hash_password,
    need,
    normalize_email,
    password_problem,
    set_cookie,
    verify_password,
)
from ..config import get_settings
from ..db import get_session
from ..models import AuditLog, AuthSession, User

public = APIRouter(prefix="/api/auth", tags=["accounts"])
router = APIRouter(prefix="/api", tags=["accounts"])


def user_json(u: User) -> dict:
    return {"id": str(u.id), "email": u.email, "name": u.name, "role": u.role, "is_active": u.is_active,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "created_at": u.created_at.isoformat() if u.created_at else None}


def principal_json(p: Principal) -> dict:
    return {"id": str(p.id) if p.id else None, "email": p.email, "name": p.name, "role": p.role, "via": p.via}


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)
    remember: bool = False


class SignupIn(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(max_length=256)


@public.get("/config", summary="What the sign-in page needs to know (no auth): only whether sign-up is open")
def auth_config():
    return {"allow_signup": get_settings().allow_signup}


@public.post("/signup", status_code=201, summary="Create an account (reviewer role) and sign in")
def signup(body: SignupIn, request: Request, response: Response, session: Session = Depends(get_session)):
    if not get_settings().allow_signup:
        raise HTTPException(403, "Sign-up is disabled. Ask an administrator for an account.")
    email = normalize_email(body.email)
    problem = password_problem(body.password, email)
    if problem:
        raise HTTPException(422, problem)
    if session.scalars(select(User).where(User.email == email)).first():
        raise HTTPException(409, "An account with this e-mail already exists.")
    user = User(email=email, name=" ".join(body.name.split()), password_hash=hash_password(body.password), role="reviewer")
    session.add(user)
    session.flush()
    token, _ = create_session(session, user, request, remember=False)
    audit(session, user, "auth.signup", "user", user.id, request=request)
    session.commit()
    set_cookie(response, token, remember=False)
    return {"user": user_json(user), "token": token}


@public.post("/login", summary="Sign in; sets an HttpOnly session cookie and also returns the token for API clients")
def login(body: LoginIn, request: Request, response: Response, session: Session = Depends(get_session)):
    email = (body.email or "").strip().lower()
    try:
        user = authenticate(session, email, body.password)
    except HTTPException as e:
        audit(session, None, "auth.login_failed", "user", email, {"reason": e.detail}, request)
        session.commit()
        raise
    token, _ = create_session(session, user, request, body.remember)
    audit(session, user, "auth.login", "user", user.id, request=request)
    session.commit()
    set_cookie(response, token, body.remember)
    return {"user": user_json(user), "token": token}


@public.post("/logout", status_code=204, summary="Revoke the current session")
def logout(request: Request, response: Response, session: Session = Depends(get_session)):
    from ..auth import COOKIE, _hash_token

    token = request.cookies.get(COOKIE)
    if token:
        session.execute(delete(AuthSession).where(AuthSession.token_hash == _hash_token(token)))
        session.commit()
    clear_cookie(response)
    response.status_code = 204
    return response


@router.get("/auth/me", summary="The signed-in user")
def me(p: Principal = Depends(get_principal)):
    return principal_json(p)


class ProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


@router.patch("/auth/me", summary="Update your display name")
def update_me(body: ProfileIn, request: Request, p: Principal = Depends(get_principal), session: Session = Depends(get_session)):
    if p.id is None:
        raise HTTPException(400, "The API key account has no profile")
    u = session.get(User, p.id)
    u.name = " ".join(body.name.split())
    audit(session, p, "user.rename", "user", u.id, request=request)
    session.commit()
    return user_json(u)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


@router.post("/auth/me/password", status_code=204, summary="Change your password (other sessions are signed out)")
def change_password(body: PasswordIn, request: Request, p: Principal = Depends(get_principal), session: Session = Depends(get_session)):
    if p.id is None:
        raise HTTPException(400, "The API key account has no password")
    u = session.get(User, p.id)
    if not verify_password(body.current_password, u.password_hash):
        raise HTTPException(403, "Current password is incorrect.")
    problem = password_problem(body.new_password, u.email)
    if problem:
        raise HTTPException(422, problem)
    from ..auth import COOKIE, _hash_token

    keep = _hash_token(request.cookies.get(COOKIE, ""))
    u.password_hash = hash_password(body.new_password)
    session.execute(delete(AuthSession).where(AuthSession.user_id == u.id, AuthSession.token_hash != keep))
    audit(session, p, "auth.password_change", "user", u.id, request=request)
    session.commit()
    return Response(status_code=204)


# ----------------------------------------------------------------- administration
class UserCreate(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(max_length=256)
    role: str = "reviewer"


class UserUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    role: str | None = None
    is_active: bool | None = None
    new_password: str | None = Field(None, max_length=256)


def _active_admins(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))) or 0


@router.get("/users", summary="List users (admin)")
def list_users(session: Session = Depends(get_session), _: Principal = Depends(need("admin"))):
    rows = session.scalars(select(User).order_by(User.created_at)).all()
    return {"users": [user_json(u) for u in rows]}


@router.post("/users", status_code=201, summary="Create a user (admin)")
def create_user(body: UserCreate, request: Request, session: Session = Depends(get_session), p: Principal = Depends(need("admin"))):
    email = normalize_email(body.email)
    if body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    problem = password_problem(body.password, email)
    if problem:
        raise HTTPException(422, problem)
    if session.scalars(select(User).where(User.email == email)).first():
        raise HTTPException(409, "An account with this e-mail already exists.")
    u = User(email=email, name=" ".join(body.name.split()), role=body.role, password_hash=hash_password(body.password))
    session.add(u)
    session.flush()
    audit(session, p, "user.create", "user", u.id, {"email": email, "role": body.role}, request)
    session.commit()
    return user_json(u)


@router.patch("/users/{user_id}", summary="Change a user's name, role, active state or password (admin)")
def update_user(user_id: uuid.UUID, body: UserUpdate, request: Request, session: Session = Depends(get_session),
                p: Principal = Depends(need("admin"))):
    u = session.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    changes: dict = {}
    if body.role is not None and body.role != u.role:
        if body.role not in ROLES:
            raise HTTPException(422, f"role must be one of {ROLES}")
        if u.role == "admin" and u.is_active and _active_admins(session) <= 1:
            raise HTTPException(409, "There must be at least one active administrator.")
        changes["role"] = [u.role, body.role]
        u.role = body.role
    if body.is_active is not None and body.is_active != u.is_active:
        if not body.is_active and (u.id == p.id or (u.role == "admin" and _active_admins(session) <= 1)):
            raise HTTPException(409, "You cannot deactivate yourself or the last administrator.")
        changes["is_active"] = body.is_active
        u.is_active = body.is_active
        if not body.is_active:
            session.execute(delete(AuthSession).where(AuthSession.user_id == u.id))
    if body.name is not None:
        u.name = " ".join(body.name.split())
        changes["name"] = u.name
    if body.new_password:
        problem = password_problem(body.new_password, u.email)
        if problem:
            raise HTTPException(422, problem)
        u.password_hash = hash_password(body.new_password)
        u.failed_attempts, u.locked_until = 0, None
        session.execute(delete(AuthSession).where(AuthSession.user_id == u.id))
        changes["password"] = "reset"
    if changes:
        audit(session, p, "user.update", "user", u.id, {"email": u.email, **changes}, request)
    session.commit()
    return user_json(u)


def _audit_json(a: AuditLog, with_ip: bool) -> dict:
    out = {"id": a.id, "action": a.action, "user": a.user_name or a.user_email, "user_email": a.user_email, "target_type": a.target_type,
           "target_id": a.target_id, "detail": a.detail, "created_at": a.created_at.isoformat()}
    if with_ip:
        out["ip"] = a.ip
    return out


@router.get("/audit", summary="Audit log (admin)")
def audit_log(action: str | None = None, user: str | None = None, days: int = Query(30, ge=1, le=365), limit: int = Query(100, le=500),
              offset: int = 0, session: Session = Depends(get_session), _: Principal = Depends(need("admin"))):
    stmt = select(AuditLog).where(AuditLog.created_at >= datetime.now(UTC) - timedelta(days=days))
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if user:
        stmt = stmt.where(AuditLog.user_email.ilike(f"%{user}%"))
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.scalars(stmt.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "events": [_audit_json(a, True) for a in rows]}


ACTIVITY_ACTIONS = ("document.", "invoice.", "compare.")


@router.get("/activity", summary="Recent team activity (any signed-in user)")
def activity(limit: int = Query(20, le=100), session: Session = Depends(get_session), _: Principal = Depends(get_principal)):
    from sqlalchemy import or_

    stmt = select(AuditLog).where(or_(*[AuditLog.action.like(f"{a}%") for a in ACTIVITY_ACTIONS])).order_by(AuditLog.id.desc()).limit(limit)
    return {"events": [_audit_json(a, False) for a in session.scalars(stmt).all()]}
