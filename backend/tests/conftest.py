"""Test configuration.

Tests run against a real PostgreSQL database (default `docintel_test`, override
with TEST_DATABASE_URL) with jobs executed inline (QUEUE_SYNC) so no Redis or
worker is needed. Documents are generated on the fly with the same renderer
as the evaluation dataset, so every test knows its exact ground truth.
"""
from __future__ import annotations

import io
import os
import random
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="docintel-test-")
os.environ.update(
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5432/docintel_test"),
    QUEUE_SYNC="true",
    STORAGE_DIR=_TMP,
    LLM_PROVIDER="rules",
    LLM_API_KEY="",
    LLM_MODEL="",
    LLM_BASE_URL="",
    API_KEY="",
    SEED_DEMO_USERS="true",
    ALLOW_SIGNUP="true",
    MODEL_DIR=os.environ.get("MODEL_DIR", str(Path(__file__).resolve().parents[1] / "storage" / "models")),
)

from eval.generate_dataset import (  # noqa: E402
    degrade,
    images_to_pdf,
    make_invoice,
    pdf_to_images,
    render_pdf,
)


@pytest.fixture(scope="session")
def rng():
    return random.Random(7)


@pytest.fixture
def invoice(rng):
    """A fresh invoice dict (ground truth) for each test."""
    return make_invoice(rng, rng.randint(0, 10_000))


def pdf_bytes(inv, template=0, date_fmt="iso", style="us", **kw) -> bytes:
    return render_pdf(inv, template, date_fmt, style, **kw)


def scan_png(inv, quality="medium", template=1) -> bytes:
    import cv2

    img = degrade(pdf_to_images(pdf_bytes(inv, template))[0], quality, random.Random(1))
    return cv2.imencode(".png", img)[1].tobytes()


def scan_pdf(inv, quality="clean") -> bytes:
    imgs = [degrade(im, quality, random.Random(2)) for im in pdf_to_images(pdf_bytes(inv))]
    return images_to_pdf(imgs)


def xlsx_bytes(sheets: dict[str, list[list]]) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


@pytest.fixture(scope="session")
def db():
    from sqlalchemy import text

    from app.db import Base, engine, init_db

    init_db()
    yield engine
    with engine.begin() as c:
        for t in reversed(Base.metadata.sorted_tables):
            c.execute(text(f"TRUNCATE {t.name} CASCADE"))


DEMO = {
    "admin": ("admin@docintel.demo", "Admin#Demo2026"),
    "reviewer": ("reviewer@docintel.demo", "Reviewer#Demo2026"),
    "viewer": ("viewer@docintel.demo", "Viewer#Demo2026"),
}


def login_as(c, role: str):
    email, pw = DEMO[role]
    r = c.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def anon(db):
    """A client with no session (fresh database, demo users seeded)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.db import Base, engine
    from app.main import app

    with engine.begin() as c:
        for t in reversed(Base.metadata.sorted_tables):
            c.execute(text(f"TRUNCATE {t.name} CASCADE"))
    from app import runtime_settings

    runtime_settings.invalidate()  # settings saved by a previous test must not leak into this one
    with TestClient(app) as c:
        yield c
    runtime_settings.invalidate()


@pytest.fixture
def client(anon):
    """Signed in as the demo administrator: the default for API tests."""
    login_as(anon, "admin")
    return anon


@pytest.fixture
def make_client(anon):
    """Factory for extra clients signed in as another role (shares the same database)."""
    from fastapi.testclient import TestClient

    from app.main import app

    opened = []

    def _make(role: str):
        c = TestClient(app)
        login_as(c, role)
        opened.append(c)
        return c

    yield _make
    for c in opened:
        c.close()
