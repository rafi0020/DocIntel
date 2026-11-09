from __future__ import annotations

import time
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..auth import Principal, audit, need
from ..config import get_settings
from ..db import get_session
from ..models import Document, Invoice, Reconciliation, ValidationIssue
from ..search.service import SearchFilters, search
from ..validation.cross import invoice_as_dict
from ..validation.reconcile import reconcile
from ..worker.queue import queue_health

router = APIRouter(prefix="/api", tags=["search & analytics"])
public = APIRouter(prefix="/api", tags=["system"])


@router.get("/search", summary="Keyword, semantic or hybrid search with filters")
def search_invoices(
    q: str | None = Query(None, max_length=500),
    mode: str = Query("hybrid", pattern="^(keyword|semantic|hybrid)$"),
    review_status: str | None = None,
    needs_review: bool | None = None,
    supplier: str | None = None,
    customer: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    min_total: float | None = None,
    max_total: float | None = None,
    currency: str | None = None,
    issue_code: str | None = None,
    file_type: str | None = None,
    record_kind: str | None = None,
    document_id: uuid.UUID | None = None,
    limit: int = Query(25, le=200),
    offset: int = 0,
    session: Session = Depends(get_session),
):
    f = SearchFilters(review_status, supplier, customer, date_from, date_to, min_total, max_total, currency, issue_code,
                      needs_review, file_type, record_kind, str(document_id) if document_id else None)
    t0 = time.perf_counter()
    res = search(session, q, mode, f, limit, offset)
    res["took_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return res


class CompareIn(BaseModel):
    left_document_id: uuid.UUID | None = None
    left_document_ids: list[uuid.UUID] | None = Field(None, max_length=1000, description="several source documents, e.g. all invoices received")
    right_document_id: uuid.UUID


@router.post("/compare", summary="Cross-verify documents (PDF↔PDF, PDF↔Excel, many invoices ↔ one ledger)")
def compare(body: CompareIn, request: Request, session: Session = Depends(get_session), principal: Principal = Depends(need("reviewer"))):
    left_ids = list(dict.fromkeys((body.left_document_ids or []) + ([body.left_document_id] if body.left_document_id else [])))
    if not left_ids:
        raise HTTPException(422, "Give left_document_id or left_document_ids")
    right = session.get(Document, body.right_document_id)
    lefts = session.scalars(select(Document).where(Document.id.in_(left_ids))).all()
    if right is None or len(lefts) != len(left_ids):
        raise HTTPException(404, "Document not found")
    if right.id in left_ids:
        raise HTTPException(400, "The reference document cannot also be a source document")
    for d in [*lefts, right]:
        if d.status in ("queued", "processing", "failed"):
            raise HTTPException(409, f"'{d.filename}' is {d.status}; it must finish processing first")
    left_recs = [invoice_as_dict(i) for d in lefts for i in d.invoices]
    res = reconcile(left_recs, [invoice_as_dict(i) for i in right.invoices], get_settings().amount_abs_tolerance)
    label = lefts[0].filename if len(lefts) == 1 else f"{len(lefts)} documents"
    res["left_document_ids"] = [str(x) for x in left_ids]
    rec = Reconciliation(left_document_id=lefts[0].id, right_document_id=right.id,
                         summary={**res["summary"], "left_label": label}, result=res)
    session.add(rec)
    session.flush()
    audit(session, principal, "compare.run", "reconciliation", rec.id, {"left": label, "right": right.filename, "mismatches": res["summary"].get("with_mismatches")}, request)
    session.commit()
    return {"id": str(rec.id), "left": {"id": str(lefts[0].id), "filename": label, "file_type": lefts[0].file_type, "count": len(lefts)},
            "right": {"id": str(right.id), "filename": right.filename, "file_type": right.file_type}, **res}


@router.get("/compare", summary="Recent cross-verification runs")
def list_compares(limit: int = 20, session: Session = Depends(get_session)):
    rows = session.scalars(select(Reconciliation).order_by(Reconciliation.created_at.desc()).limit(limit)).all()
    names = dict(session.execute(select(Document.id, Document.filename)).all())
    return [{"id": str(r.id), "left_document_id": str(r.left_document_id), "right_document_id": str(r.right_document_id),
             "left_filename": (r.summary or {}).get("left_label") or names.get(r.left_document_id), "right_filename": names.get(r.right_document_id),
             "left_document_ids": (r.result or {}).get("left_document_ids", [str(r.left_document_id)]),
             "summary": r.summary, "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/stats", summary="Dashboard numbers")
def stats(session: Session = Depends(get_session)):
    by_status = dict(session.execute(select(Document.status, func.count()).group_by(Document.status)).all())
    by_review = dict(session.execute(select(Invoice.review_status, func.count()).group_by(Invoice.review_status)).all())
    issues = session.execute(
        select(ValidationIssue.code, ValidationIssue.severity, func.count())
        .where(ValidationIssue.resolved.is_(False), ValidationIssue.severity != "info")
        .group_by(ValidationIssue.code, ValidationIssue.severity).order_by(func.count().desc()).limit(12)
    ).all()
    perf = session.execute(
        select(Document.source_kind, func.count(), func.avg(Document.processing_ms),
               func.percentile_cont(0.95).within_group(Document.processing_ms), func.sum(Document.page_count))
        .where(Document.processing_ms.is_not(None), Document.status != "failed").group_by(Document.source_kind)
    ).all()
    totals = session.execute(select(Invoice.currency, func.count(), func.sum(Invoice.total))
                             .where(Invoice.record_kind == "document").group_by(Invoice.currency)).all()
    return {
        "documents": {"total": sum(by_status.values()), "by_status": by_status},
        "records": {"total": sum(by_review.values()), "by_review_status": by_review},
        "top_issues": [{"code": c, "severity": s, "count": n} for c, s, n in issues],
        "performance": [{"source_kind": k, "documents": n, "avg_ms": round(float(a or 0)), "p95_ms": round(float(p or 0)),
                         "pages": int(pg or 0)} for k, n, a, p, pg in perf],
        "amounts_by_currency": [{"currency": c, "invoices": n, "total": round(float(t or 0), 2)} for c, n, t in totals],
    }


@public.get("/health", summary="Liveness / dependency check (no auth)")
def health(session: Session = Depends(get_session)):
    from ..runtime_settings import effective_settings

    s = effective_settings()
    try:
        session.execute(text("select 1"))
        db = {"ok": True}
    except Exception as e:  # noqa: BLE001
        db = {"ok": False, "error": str(e)}
    return {"status": "ok" if db["ok"] else "degraded", "database": db, "queue": queue_health(),
            "extraction": {"llm_provider": s.llm_provider, "llm_model": s.llm_model, "ocr_engine": s.ocr_engine},
            "auth_required": True, "signup_enabled": s.allow_signup}


@router.get("/analytics", summary="Dashboard analytics: volumes over time, quality mix, spend, speed and team activity")
def analytics(days: int = Query(30, ge=7, le=365), session: Session = Depends(get_session)):
    from datetime import UTC, datetime, timedelta

    from ..models import AuditLog

    since = datetime.now(UTC) - timedelta(days=days)
    daily = session.execute(text("""
        WITH d AS (SELECT generate_series(date_trunc('day', now() - make_interval(days => :n - 1)), date_trunc('day', now()), '1 day') AS day)
        SELECT d.day::date AS day,
               (SELECT count(*) FROM documents x WHERE date_trunc('day', x.created_at) = d.day) AS documents,
               (SELECT count(*) FROM documents x WHERE date_trunc('day', x.created_at) = d.day AND x.status = 'failed') AS failed,
               (SELECT count(*) FROM invoices i WHERE date_trunc('day', i.created_at) = d.day) AS records
        FROM d ORDER BY d.day"""), {"n": days}).all()
    by_status = dict(session.execute(select(Document.status, func.count()).group_by(Document.status)).all())
    by_review = dict(session.execute(select(Invoice.review_status, func.count()).group_by(Invoice.review_status)).all())
    by_kind = dict(session.execute(select(Document.source_kind, func.count()).where(Document.source_kind.is_not(None)).group_by(Document.source_kind)).all())
    n_docs = sum(by_status.values())
    n_rec = sum(by_review.values())
    clean = sum(by_review.get(k, 0) for k in ("auto_approved", "approved", "corrected"))
    avg_ms = session.scalar(select(func.avg(Document.processing_ms)).where(Document.processing_ms.is_not(None), Document.status != "failed"))
    open_issues = session.scalar(select(func.count()).select_from(ValidationIssue).where(ValidationIssue.resolved.is_(False), ValidationIssue.severity == "error")) or 0

    spend = []
    for cur, in session.execute(select(Invoice.currency).where(Invoice.record_kind == "document", Invoice.currency.is_not(None))
                                .group_by(Invoice.currency).order_by(func.sum(Invoice.total).desc()).limit(4)).all():
        top = session.execute(select(Invoice.supplier_name, func.count(), func.sum(Invoice.total))
                              .where(Invoice.record_kind == "document", Invoice.currency == cur, Invoice.supplier_name.is_not(None))
                              .group_by(Invoice.supplier_name).order_by(func.sum(Invoice.total).desc()).limit(5)).all()
        total = session.scalar(select(func.sum(Invoice.total)).where(Invoice.record_kind == "document", Invoice.currency == cur))
        spend.append({"currency": cur, "total": round(float(total or 0), 2),
                      "suppliers": [{"name": n, "invoices": c, "total": round(float(t or 0), 2)} for n, c, t in top]})

    issues = session.execute(
        select(ValidationIssue.code, ValidationIssue.severity, func.count()).where(ValidationIssue.resolved.is_(False), ValidationIssue.severity != "info")
        .group_by(ValidationIssue.code, ValidationIssue.severity).order_by(func.count().desc()).limit(8)).all()
    team = session.execute(
        select(AuditLog.user_name, AuditLog.user_email, AuditLog.action, func.count())
        .where(AuditLog.created_at >= since, AuditLog.action.in_(("document.upload", "invoice.approve", "invoice.correct", "invoice.bulk_approve")))
        .group_by(AuditLog.user_name, AuditLog.user_email, AuditLog.action)).all()
    people: dict[str, dict] = {}
    for name, email, action, n in team:
        row = people.setdefault(email or name or "unknown", {"user": name or email, "uploads": 0, "approvals": 0, "corrections": 0})
        row["uploads" if action == "document.upload" else "corrections" if action == "invoice.correct" else "approvals"] += n

    return {
        "days": days,
        "kpis": {"documents": n_docs, "records": n_rec, "success_rate": round(100 * (1 - by_status.get("failed", 0) / n_docs), 1) if n_docs else None,
                 "clean_rate": round(100 * clean / n_rec, 1) if n_rec else None, "avg_processing_ms": round(float(avg_ms)) if avg_ms else None,
                 "open_errors": open_issues, "needs_review": by_review.get("needs_review", 0)},
        "daily": [{"day": d.isoformat(), "documents": a, "failed": f, "records": r} for d, a, f, r in daily],
        "review_mix": by_review,
        "document_status": by_status,
        "source_kinds": by_kind,
        "spend": spend,
        "issues": [{"code": c, "severity": s, "count": n} for c, s, n in issues],
        "team": sorted(people.values(), key=lambda r: -(r["uploads"] + r["approvals"] + r["corrections"]))[:8],
    }
