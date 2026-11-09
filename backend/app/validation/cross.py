"""Validation rules that need other records: duplicates and ledger cross-checks."""
from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Document, Invoice, ValidationIssue
from .reconcile import compare_records
from .rules import needs_review

CROSS_CODES = {"duplicate_invoice", "duplicate_file", "possible_duplicate", "ledger_mismatch", "ledger_match"}


def invoice_as_dict(inv: Invoice) -> dict:
    return {
        "id": str(inv.id),
        "invoice_number": inv.invoice_number,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "supplier_name": inv.supplier_name,
        "customer_name": inv.customer_name,
        "subtotal": float(inv.subtotal) if inv.subtotal is not None else None,
        "tax": float(inv.tax) if inv.tax is not None else None,
        "total": float(inv.total) if inv.total is not None else None,
        "currency": inv.currency,
        "line_items": inv.line_items or [],
        "document_id": str(inv.document_id),
        "sheet_name": inv.sheet_name,
    }


def _add(session: Session, inv: Invoice, code: str, severity: str, message: str, field: str | None = None, details: dict | None = None):
    session.add(ValidationIssue(invoice_id=inv.id, code=code, severity=severity, field=field, message=message, details=details or {}))


def refresh_review_state(session: Session, inv: Invoice) -> None:
    session.flush()
    issues = session.scalars(select(ValidationIssue).where(ValidationIssue.invoice_id == inv.id, ValidationIssue.resolved.is_(False))).all()
    flagged = needs_review([{"severity": i.severity} for i in issues])
    if inv.review_status in ("approved",):
        return
    inv.needs_review = flagged
    if flagged:
        inv.review_status = "needs_review"
    elif inv.review_status != "corrected":
        inv.review_status = "auto_approved"


def run_cross_checks(session: Session, doc: Document) -> set[uuid.UUID]:
    """Add cross-record issues for every invoice of `doc`. Returns ids of other invoices touched."""
    tol = get_settings().amount_abs_tolerance
    touched: set[uuid.UUID] = set()
    invoices = list(doc.invoices)

    # remove previous cross-record issues that mention this document (re-processing)
    for inv in invoices:
        for iss in list(inv.issues):
            if iss.code in CROSS_CODES:
                session.delete(iss)
    session.flush()

    same_file = session.scalars(
        select(Document).where(Document.sha256 == doc.sha256, Document.id != doc.id).order_by(Document.created_at)
    ).first()

    seen_in_doc: dict[str, Invoice] = {}
    for inv in invoices:
        if same_file is not None:
            _add(session, inv, "duplicate_file", "warning",
                 f"The same file was already uploaded as '{same_file.filename}'.", None,
                 {"document_id": str(same_file.id), "filename": same_file.filename})
        num = inv.invoice_number_norm
        if num:
            # a workbook may list the same invoice on a ledger sheet and an items sheet
            key = f"{inv.sheet_name or ''}|{num}"
            prev = seen_in_doc.get(key)
            if prev is not None:
                _add(session, inv, "duplicate_invoice", "error",
                     f"Invoice {inv.invoice_number} appears more than once in this file.", "invoice_number",
                     {"invoice_id": str(prev.id), "document_id": str(doc.id)})
            seen_in_doc.setdefault(key, inv)

        if inv.record_kind == "document" and num:
            # same invoice number from the same (or unknown) supplier in another document
            q = select(Invoice, Document.filename).join(Document).where(
                Invoice.invoice_number_norm == num,
                Invoice.record_kind == "document",
                Invoice.document_id != doc.id,
                Document.created_at <= doc.created_at,
            )
            if inv.supplier_norm:
                q = q.where(or_(Invoice.supplier_norm == inv.supplier_norm, Invoice.supplier_norm.is_(None)))
            other = session.execute(q.order_by(Document.created_at)).first()
            if other:
                o, fname = other
                _add(session, inv, "duplicate_invoice", "error",
                     f"Invoice {inv.invoice_number} was already received in '{fname}'.", "invoice_number",
                     {"invoice_id": str(o.id), "document_id": str(o.document_id), "filename": fname})

        if inv.record_kind == "document" and inv.supplier_norm and inv.total is not None and inv.invoice_date:
            q = select(Invoice, Document.filename).join(Document).where(
                Invoice.record_kind == "document",
                Invoice.document_id != doc.id,
                Invoice.supplier_norm == inv.supplier_norm,
                Invoice.total == inv.total,
                Invoice.invoice_date == inv.invoice_date,
                or_(Invoice.invoice_number_norm.is_(None), Invoice.invoice_number_norm != (num or "")),
            )
            other = session.execute(q).first()
            if other:
                o, fname = other
                _add(session, inv, "possible_duplicate", "warning",
                     f"Same supplier, date and total as invoice {o.invoice_number or '(no number)'} in '{fname}'.", None,
                     {"invoice_id": str(o.id), "filename": fname})

        # ledger cross-check (document <-> spreadsheet ledger row with the same number)
        if num:
            other_kind = "ledger_row" if inv.record_kind == "document" else "document"
            rows = session.execute(
                select(Invoice, Document.filename).join(Document).where(
                    Invoice.invoice_number_norm == num, Invoice.record_kind == other_kind, Invoice.document_id != doc.id
                )
            ).all()
            for o, fname in rows:
                # clear stale cross-check issues on the other side for this pair
                for iss in list(o.issues):
                    if iss.code in ("ledger_mismatch", "ledger_match") and (iss.details or {}).get("invoice_id") == str(inv.id):
                        session.delete(iss)
                doc_side, led_side = (inv, o) if inv.record_kind == "document" else (o, inv)
                res = compare_records(invoice_as_dict(doc_side), invoice_as_dict(led_side), tol)
                bad = [d for d in res["fields"] if d["status"] == "mismatch"]
                for me, them, them_name in ((inv, o, fname), (o, inv, doc.filename)):
                    if bad:
                        desc = "; ".join(f"{d['field']}: {d['left']} vs {d['right']}" for d in bad[:4])
                        _add(session, me, "ledger_mismatch", "error",
                             f"Does not match {'ledger' if me is doc_side else 'invoice document'} '{them_name}': {desc}.",
                             bad[0]["field"], {"invoice_id": str(them.id), "filename": them_name, "differences": bad})
                    else:
                        _add(session, me, "ledger_match", "info",
                             f"Cross-checked against '{them_name}': all compared fields match.", None,
                             {"invoice_id": str(them.id), "filename": them_name})
                touched.add(o.id)

    session.flush()
    for inv in invoices:
        session.refresh(inv)
        refresh_review_state(session, inv)
    other_docs: set[uuid.UUID] = set()
    for oid in touched:
        o = session.get(Invoice, oid)
        if o is not None:
            session.refresh(o)
            refresh_review_state(session, o)
            other_docs.add(o.document_id)
    # a new ledger can change the outcome for invoices filed earlier: update their documents too
    session.flush()
    for did in other_docs - {doc.id}:
        d = session.get(Document, did)
        if d is not None and d.status in ("completed", "needs_review"):
            session.refresh(d)
            d.status = "needs_review" if any(i.needs_review for i in d.invoices) else "completed"
    return touched

