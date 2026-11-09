"""Accounts, roles, sessions, audit log, bulk actions, analytics and export."""
from __future__ import annotations

import pytest

from tests.conftest import DEMO, login_as, pdf_bytes


def up(c, name, data):
    return c.post("/api/documents", files=[("files", (name, data))])


# ------------------------------------------------------------------ authentication
def test_every_data_endpoint_requires_sign_in(anon):
    for path in ("/api/documents", "/api/stats", "/api/search", "/api/analytics", "/api/users", "/api/audit", "/api/export", "/api/auth/me"):
        assert anon.get(path).status_code == 401, path
    assert anon.get("/api/health").status_code == 200  # health stays public
    cfg = anon.get("/api/auth/config").json()
    assert cfg == {"allow_signup": True}  # nothing about accounts or passwords is ever advertised
    assert "docintel.demo" not in anon.get("/api/auth/config").text


def test_login_me_logout_cycle(anon):
    r = anon.post("/api/auth/login", json={"email": "ADMIN@docintel.demo ", "password": DEMO["admin"][1]})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=lax" in r.headers["set-cookie"].lower()
    assert anon.get("/api/auth/me").json()["email"] == "admin@docintel.demo"
    assert anon.post("/api/auth/logout").status_code == 204
    assert anon.get("/api/auth/me").status_code == 401  # the session is revoked server-side


def test_bearer_token_works_for_api_clients(anon):
    token = anon.post("/api/auth/login", json={"email": DEMO["viewer"][0], "password": DEMO["viewer"][1]}).json()["token"]
    anon.cookies.clear()
    assert anon.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["role"] == "viewer"
    assert anon.get("/api/auth/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_wrong_password_is_generic_and_locks_after_repeated_failures(anon):
    email = DEMO["reviewer"][0]
    for _ in range(5):
        r = anon.post("/api/auth/login", json={"email": email, "password": "wrong-password-1"})
        assert r.status_code == 401 and r.json()["detail"] == "Invalid e-mail or password."
    assert anon.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x"}).json()["detail"] == "Invalid e-mail or password."
    locked = anon.post("/api/auth/login", json={"email": email, "password": DEMO["reviewer"][1]})
    assert locked.status_code == 429  # even the right password is refused while locked


def test_signup_creates_reviewer_and_validates_input(anon):
    bad = anon.post("/api/auth/signup", json={"email": "not-an-email", "name": "Sam", "password": "Abcdefgh12"})
    assert bad.status_code == 422
    weak = anon.post("/api/auth/signup", json={"email": "sam@example.com", "name": "Sam", "password": "short"})
    assert weak.status_code == 422 and "10 characters" in weak.json()["detail"]
    nodigit = anon.post("/api/auth/signup", json={"email": "sam@example.com", "name": "Sam", "password": "onlyletterspassword"})
    assert nodigit.status_code == 422
    ok = anon.post("/api/auth/signup", json={"email": "Sam@Example.com", "name": "Sam Lee", "password": "Correct-horse-9"})
    assert ok.status_code == 201 and ok.json()["user"]["role"] == "reviewer"
    assert anon.get("/api/auth/me").json()["email"] == "sam@example.com"  # signed in straight away
    dup = anon.post("/api/auth/signup", json={"email": "sam@example.com", "name": "Sam", "password": "Correct-horse-9"})
    assert dup.status_code == 409


def test_signup_can_be_disabled(anon, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "allow_signup", False)
    assert anon.post("/api/auth/signup", json={"email": "a@example.com", "name": "Ann", "password": "Correct-horse-9"}).status_code == 403


def test_passwords_are_hashed_with_scrypt(anon):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as s:
        h = s.scalars(select(User).where(User.email == DEMO["admin"][0])).one().password_hash
    assert h.startswith("scrypt$") and DEMO["admin"][1] not in h


def test_change_password_signs_out_other_sessions(anon, make_client):
    other = make_client("reviewer")
    login_as(anon, "reviewer")
    new = "Brand-new-pass-7"
    assert anon.post("/api/auth/me/password", json={"current_password": "wrong", "new_password": new}).status_code == 403
    assert anon.post("/api/auth/me/password", json={"current_password": DEMO["reviewer"][1], "new_password": new}).status_code == 204
    assert anon.get("/api/auth/me").status_code == 200  # this session survives
    assert other.get("/api/auth/me").status_code == 401  # the other one does not
    assert anon.post("/api/auth/login", json={"email": DEMO["reviewer"][0], "password": new}).status_code == 200


def test_cookie_requests_from_foreign_origins_are_blocked(client):
    r = client.post("/api/documents/reprocess-failed", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/documents/reprocess-failed", headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 200


# ------------------------------------------------------------------ roles
def test_viewer_is_read_only(anon, make_client, invoice):
    viewer = make_client("viewer")
    assert viewer.get("/api/documents").status_code == 200
    r = up(viewer, "a.pdf", pdf_bytes(invoice))
    assert r.status_code == 403 and "Reviewer access" in r.json()["detail"]
    assert viewer.post("/api/documents/reprocess-failed").status_code == 403
    assert viewer.get("/api/users").status_code == 403 and viewer.get("/api/audit").status_code == 403


def test_reviewer_can_work_but_only_delete_own_uploads(anon, make_client, invoice, rng):
    from tests.conftest import make_invoice

    admin, rev = make_client("admin"), make_client("reviewer")
    mine = up(rev, "mine.pdf", pdf_bytes(invoice)).json()["documents"][0]
    theirs = up(admin, "theirs.pdf", pdf_bytes(make_invoice(rng, 77))).json()["documents"][0]
    assert mine["uploaded_by"] == "Demo Reviewer"
    assert rev.delete(f"/api/documents/{theirs['id']}").status_code == 403
    assert rev.delete(f"/api/documents/{mine['id']}").status_code == 204
    assert admin.delete(f"/api/documents/{theirs['id']}").status_code == 204


def test_corrections_and_approvals_record_the_signed_in_user(client, invoice):
    doc = up(client, "a.pdf", pdf_bytes(invoice)).json()["documents"][0]
    rec = client.get(f"/api/documents/{doc['id']}/results").json()["records"][0]
    out = client.patch(f"/api/invoices/{rec['id']}", json={"fields": {"supplier_name": "Acme Care Ltd"}, "reviewer": "someone-else"}).json()
    assert out["corrections"][-1]["corrected_by"] == "Demo Admin"  # the client cannot impersonate another reviewer
    actions = [e["action"] for e in client.get("/api/audit").json()["events"]]
    assert {"auth.login", "document.upload", "invoice.correct"} <= set(actions)


def test_api_key_service_account(anon, monkeypatch, invoice):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "api_key", "service-key-123")
    assert anon.get("/api/documents", headers={"X-API-Key": "bad"}).status_code == 401
    assert up_with_key(anon, invoice).status_code == 202
    assert anon.get("/api/users", headers={"X-API-Key": "service-key-123"}).status_code == 403  # reviewer rights only


def up_with_key(c, invoice):
    return c.post("/api/documents", files=[("files", ("k.pdf", pdf_bytes(invoice)))], headers={"X-API-Key": "service-key-123"})


# ------------------------------------------------------------------ administration
def test_admin_manages_users_and_protects_the_last_admin(client):
    users = client.get("/api/users").json()["users"]
    admin = next(u for u in users if u["role"] == "admin")
    assert client.patch(f"/api/users/{admin['id']}", json={"role": "viewer"}).status_code == 409
    assert client.patch(f"/api/users/{admin['id']}", json={"is_active": False}).status_code == 409
    new = client.post("/api/users", json={"email": "ops@example.com", "name": "Ops Lead", "password": "Correct-horse-9", "role": "viewer"})
    assert new.status_code == 201
    uid = new.json()["id"]
    assert client.patch(f"/api/users/{uid}", json={"role": "admin"}).json()["role"] == "admin"
    assert client.post("/api/users", json={"email": "x@example.com", "name": "X Y", "password": "Correct-horse-9", "role": "root"}).status_code == 422
    assert client.patch(f"/api/users/{admin['id']}", json={"role": "viewer"}).status_code == 200  # allowed now: another admin exists


def test_deactivating_a_user_revokes_their_session(anon, make_client):
    admin, rev = make_client("admin"), make_client("reviewer")
    uid = rev.get("/api/auth/me").json()["id"]
    assert admin.patch(f"/api/users/{uid}", json={"is_active": False}).status_code == 200
    assert rev.get("/api/documents").status_code == 401
    r = anon.post("/api/auth/login", json={"email": DEMO["reviewer"][0], "password": DEMO["reviewer"][1]})
    assert r.status_code == 403
    assert admin.patch(f"/api/users/{uid}", json={"is_active": True, "new_password": "Reset-by-admin-5"}).status_code == 200
    assert anon.post("/api/auth/login", json={"email": DEMO["reviewer"][0], "password": "Reset-by-admin-5"}).status_code == 200


def test_audit_log_is_admin_only_and_activity_feed_hides_ips(anon, make_client, invoice):
    admin, rev = make_client("admin"), make_client("reviewer")
    up(rev, "a.pdf", pdf_bytes(invoice))
    ev = admin.get("/api/audit?action=document").json()["events"][0]
    assert ev["action"] == "document.upload" and ev["user_email"] == DEMO["reviewer"][0] and "ip" in ev
    feed = rev.get("/api/activity").json()["events"]
    assert feed and all("ip" not in e for e in feed)
    anon.post("/api/auth/login", json={"email": "ghost@example.com", "password": "x"})
    assert any(e["action"] == "auth.login_failed" for e in admin.get("/api/audit?action=auth").json()["events"])


# ------------------------------------------------------------------ bulk, analytics, export
def test_bulk_reprocess_delete_and_approve(client, invoice, rng):
    from tests.conftest import make_invoice

    ids = [up(client, f"{i}.pdf", pdf_bytes(make_invoice(rng, 300 + i))).json()["documents"][0]["id"] for i in range(3)]
    r = client.post("/api/documents/bulk", json={"ids": ids, "action": "reprocess"}).json()
    assert len(r["done"]) == 3 and r["skipped"] == []
    recs = [client.get(f"/api/documents/{i}/results").json()["records"][0]["id"] for i in ids]
    out = client.post("/api/invoices/bulk-approve", json={"ids": recs}).json()
    assert len(out["approved"]) + len(out["skipped"]) == 3
    assert set(client.post("/api/documents/bulk", json={"ids": ids, "action": "delete"}).json()["done"]) == set(ids)
    assert client.get("/api/documents").json()["total"] == 0
    assert client.post("/api/documents/bulk", json={"ids": ids, "action": "explode"}).status_code == 422


def test_analytics_shape(client, invoice):
    up(client, "a.pdf", pdf_bytes(invoice))
    a = client.get("/api/analytics?days=14").json()
    assert len(a["daily"]) == 14 and a["daily"][-1]["documents"] == 1
    assert a["kpis"]["documents"] == 1 and a["kpis"]["success_rate"] == 100.0
    assert a["spend"] and a["team"][0]["uploads"] == 1


@pytest.mark.parametrize("fmt,ctype", [("csv", "text/csv"), ("json", "application/json"), ("xlsx", "spreadsheetml")])
def test_export_formats(client, invoice, fmt, ctype):
    up(client, "a.pdf", pdf_bytes(invoice))
    r = client.get(f"/api/export?format={fmt}")
    assert r.status_code == 200 and ctype in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    if fmt == "csv":
        assert invoice["invoice_number"] in r.text


def test_export_neutralises_spreadsheet_formulas(client, invoice):
    doc = up(client, "a.pdf", pdf_bytes(invoice)).json()["documents"][0]
    rec = client.get(f"/api/documents/{doc['id']}/results").json()["records"][0]
    client.patch(f"/api/invoices/{rec['id']}", json={"fields": {"supplier_name": "=HYPERLINK(\"http://x\")"}})
    body = client.get("/api/export?format=csv").text
    assert "'=HYPERLINK" in body and ",=HYPERLINK" not in body


def test_bootstrap_admin_is_created_only_when_no_admin_exists(anon, monkeypatch):
    from sqlalchemy import select, text

    from app.auth import ensure_bootstrap_admin
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import User

    st = get_settings()
    monkeypatch.setattr(st, "bootstrap_admin_email", "boss@example.com")
    monkeypatch.setattr(st, "bootstrap_admin_password", "Correct-horse-9")
    with SessionLocal() as s:
        ensure_bootstrap_admin(s)  # demo admin exists, so nothing is added
        assert s.scalars(select(User).where(User.email == "boss@example.com")).first() is None
        s.execute(text("DELETE FROM users WHERE role = 'admin'"))
        s.commit()
        ensure_bootstrap_admin(s)
        assert s.scalars(select(User).where(User.email == "boss@example.com")).one().role == "admin"
    anon.cookies.clear()
    assert anon.post("/api/auth/login", json={"email": "boss@example.com", "password": "Correct-horse-9"}).status_code == 200
