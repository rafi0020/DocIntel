from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Principal, audit, need
from ..db import get_session
from ..extraction.normalize import parse_amount, parse_date
from ..extraction.schema import (
    AMOUNT_FIELDS,
    FIELDS,
    ExtractedInvoice,
    FieldValue,
    LineItem,
)
from ..models import Correction, Document, Invoice, ValidationIssue
from ..search.embed import embed, invoice_search_text
from ..validation.cross import CROSS_CODES, refresh_review_state, run_cross_checks
from ..validation.rules import validate_record
from ..worker.tasks import apply_extraction
from .serializers import invoice_json

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


class LineItemIn(BaseModel):
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None


class CorrectionIn(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict, description="field -> corrected value (null clears it)")
    line_items: list[LineItemIn] | None = None
    reviewer: str | None = Field(None, max_length=128, description="ignored: the signed-in user is recorded")
    note: str | None = Field(None, max_length=2000)


def _get(session: Session, inv_id: uuid.UUID) -> Invoice:
    inv = session.get(Invoice, inv_id)
    if inv is None:
        raise HTTPException(404, "Invoice record not found")
    return inv


def _clean(field: str, raw: Any):
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if field in AMOUNT_FIELDS:
        a = parse_amount(raw)
        if a is None:
            raise HTTPException(422, f"'{raw}' is not a valid amount for {field}")
        return float(a)
    if field == "invoice_date":
        d, _ = parse_date(raw, "MDY")
        if d is None:
            raise HTTPException(422, f"'{raw}' is not a valid date")
        return d.isoformat()
    if field == "currency":
        v = str(raw).strip().upper()
        if len(v) != 3 or not v.isalpha():
            raise HTTPException(422, "currency must be a 3-letter ISO code")
        return v
    return " ".join(str(raw).split())[:512]


def to_extracted(inv: Invoice) -> ExtractedInvoice:
    return ExtractedInvoice(
        fields={k: FieldValue(**(inv.fields or {}).get(k, {})) for k in FIELDS},
        line_items=[LineItem(**li) for li in (inv.line_items or [])],
        record_kind=inv.record_kind, page_start=inv.page_start, page_end=inv.page_end,
        sheet_name=inv.sheet_name, row_index=inv.row_index, raw_text=inv.raw_text or "", extractor=inv.extractor or "",
    )


def revalidate(session: Session, inv: Invoice) -> None:
    ex = to_extracted(inv)
    for iss in list(inv.issues):
        if iss.code not in CROSS_CODES:
            session.delete(iss)
    session.flush()
    for i in validate_record(ex):
        if i.code == "llm_fallback":
            continue
        session.add(ValidationIssue(invoice_id=inv.id, code=i.code, severity=i.severity, field=i.field, message=i.message, details=i.details))
    session.flush()
    doc = session.get(Document, inv.document_id)
    session.refresh(doc)
    run_cross_checks(session, doc)
    session.refresh(inv)
    refresh_review_state(session, inv)
    doc.status = "needs_review" if any(i.needs_review for i in doc.invoices) else "completed"


@router.get("/{inv_id}", summary="One extracted record with field provenance, issues and correction history")
def get_invoice(inv_id: uuid.UUID, session: Session = Depends(get_session)):
    return invoice_json(_get(session, inv_id))


@router.patch("/{inv_id}", summary="Manually correct fields / line items (audited, re-validated)")
def correct_invoice(inv_id: uuid.UUID, body: CorrectionIn, request: Request, session: Session = Depends(get_session),
                    principal: Principal = Depends(need("reviewer"))):
    inv = _get(session, inv_id)
    who = principal.name
    unknown = set(body.fields) - set(FIELDS)
    if unknown:
        raise HTTPException(422, f"Unknown fields: {sorted(unknown)}")
    fields = dict(inv.fields or {})
    changed = 0
    for name, raw in body.fields.items():
        new = _clean(name, raw)
        old = fields.get(name) or {}
        if old.get("value") == new:
            continue
        session.add(Correction(invoice_id=inv.id, field=name, old_value={"value": old.get("value")}, new_value={"value": new},
                               corrected_by=who, note=body.note))
        fields[name] = {**FieldValue().model_dump(), "value": new, "confidence": 1.0 if new is not None else 0.0,
                        "source": old.get("source"), "method": "manual", "note": f"Corrected by {who}"}
        changed += 1
    if body.line_items is not None:
        new_items = [{**li.model_dump(), "confidence": 1.0, "source": None} for li in body.line_items]
        session.add(Correction(invoice_id=inv.id, field="line_items", old_value={"value": inv.line_items},
                               new_value={"value": new_items}, corrected_by=who, note=body.note))
        inv.line_items = new_items
        changed += 1
    if not changed:
        return invoice_json(inv)
    inv.fields = fields
    ex = to_extracted(inv)
    apply_extraction(inv, ex)
    kw, sem = invoice_search_text(inv.fields, inv.line_items, inv.raw_text or "", "")
    inv.search_text = kw
    vec = embed([sem])
    if vec:
        inv.embedding = vec[0]
    inv.review_status = "corrected"
    revalidate(session, inv)
    audit(session, principal, "invoice.correct", "invoice", inv.id, {"invoice_number": inv.invoice_number, "changes": changed}, request)
    session.commit()
    session.refresh(inv)
    return invoice_json(inv)


@router.post("/{inv_id}/approve", summary="Reviewer approves the record (clears the review flag)")
def approve(inv_id: uuid.UUID, request: Request, session: Session = Depends(get_session), principal: Principal = Depends(need("reviewer"))):
    inv = _get(session, inv_id)
    session.add(Correction(invoice_id=inv.id, field="_status", old_value={"value": inv.review_status},
                           new_value={"value": "approved"}, corrected_by=principal.name[:128], note="Approved after review"))
    audit(session, principal, "invoice.approve", "invoice", inv.id, {"invoice_number": inv.invoice_number}, request)
    inv.review_status, inv.needs_review = "approved", False
    doc = session.get(Document, inv.document_id)
    session.flush()
    session.refresh(doc)
    doc.status = "needs_review" if any(i.needs_review for i in doc.invoices) else "completed"
    session.commit()
    session.refresh(inv)
    return invoice_json(inv)


@router.post("/{inv_id}/issues/{issue_id}/resolve", summary="Mark one validation issue as resolved")
def resolve_issue(inv_id: uuid.UUID, issue_id: int, request: Request, session: Session = Depends(get_session),
                  principal: Principal = Depends(need("reviewer"))):
    iss = session.scalars(select(ValidationIssue).where(ValidationIssue.id == issue_id, ValidationIssue.invoice_id == inv_id)).first()
    if iss is None:
        raise HTTPException(404, "Issue not found")
    iss.resolved = True
    inv = _get(session, inv_id)
    audit(session, principal, "invoice.resolve_issue", "invoice", inv.id, {"code": iss.code}, request)
    refresh_review_state(session, inv)
    session.commit()
    session.refresh(inv)
    return invoice_json(inv)


class BulkApproveIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


@router.post("/bulk-approve", summary="Approve many records at once (only records without open errors)")
def bulk_approve(body: BulkApproveIn, request: Request, session: Session = Depends(get_session), principal: Principal = Depends(need("reviewer"))):
    invs = session.scalars(select(Invoice).where(Invoice.id.in_(body.ids))).all()
    approved, skipped = [], []
    docs: dict[uuid.UUID, Document] = {}
    for inv in invs:
        has_error = any(i.severity == "error" and not i.resolved for i in inv.issues)
        if has_error:
            skipped.append({"id": str(inv.id), "reason": "has open errors"})
            continue
        session.add(Correction(invoice_id=inv.id, field="_status", old_value={"value": inv.review_status}, new_value={"value": "approved"},
                               corrected_by=principal.name[:128], note="Approved in bulk"))
        inv.review_status, inv.needs_review = "approved", False
        docs[inv.document_id] = session.get(Document, inv.document_id)
        approved.append(str(inv.id))
    session.flush()
    for d in docs.values():
        session.refresh(d)
        d.status = "needs_review" if any(i.needs_review for i in d.invoices) else "completed"
    if approved:
        audit(session, principal, "invoice.bulk_approve", "invoice", None, {"count": len(approved)}, request)
    session.commit()
    return {"approved": approved, "skipped": skipped}
