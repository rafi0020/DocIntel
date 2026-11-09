from __future__ import annotations

from ..models import Document, Invoice, ProcessingEvent


def doc_summary(d: Document) -> dict:
    return {
        "id": str(d.id),
        "filename": d.filename,
        "file_type": d.file_type,
        "size_bytes": d.size_bytes,
        "status": d.status,
        "stage": d.stage,
        "progress": d.progress,
        "source_kind": d.source_kind,
        "page_count": d.page_count,
        "invoice_count": d.invoice_count,
        "error_code": d.error_code,
        "error_message": d.error_message,
        "attempts": d.attempts,
        "processing_ms": d.processing_ms,
        "extractor": d.extractor,
        "uploaded_by": (d.uploader.name if d.uploader else None),
        "uploaded_by_id": str(d.uploaded_by_id) if d.uploaded_by_id else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "finished_at": d.finished_at.isoformat() if d.finished_at else None,
    }


def event_json(e: ProcessingEvent) -> dict:
    return {"id": e.id, "attempt": e.attempt, "stage": e.stage, "status": e.status, "message": e.message,
            "duration_ms": e.duration_ms, "created_at": e.created_at.isoformat() if e.created_at else None}


def invoice_json(inv: Invoice, full: bool = True) -> dict:
    out = {
        "id": str(inv.id),
        "document_id": str(inv.document_id),
        "position": inv.position,
        "record_kind": inv.record_kind,
        "page_start": inv.page_start,
        "page_end": inv.page_end,
        "sheet_name": inv.sheet_name,
        "row_index": inv.row_index,
        "invoice_number": inv.invoice_number,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "supplier_name": inv.supplier_name,
        "customer_name": inv.customer_name,
        "subtotal": float(inv.subtotal) if inv.subtotal is not None else None,
        "tax": float(inv.tax) if inv.tax is not None else None,
        "total": float(inv.total) if inv.total is not None else None,
        "currency": inv.currency,
        "confidence": inv.confidence,
        "review_status": inv.review_status,
        "needs_review": inv.needs_review,
        "extractor": inv.extractor,
        "issue_counts": {
            sev: sum(1 for i in inv.issues if i.severity == sev and not i.resolved) for sev in ("error", "warning", "info")
        },
    }
    if full:
        out["fields"] = inv.fields
        out["line_items"] = inv.line_items
        out["issues"] = [
            {"id": i.id, "code": i.code, "severity": i.severity, "field": i.field, "message": i.message,
             "details": i.details, "resolved": i.resolved}
            for i in sorted(inv.issues, key=lambda x: ({"error": 0, "warning": 1, "info": 2}.get(x.severity, 3), x.id or 0))
        ]
        out["corrections"] = [
            {"id": c.id, "field": c.field, "old_value": c.old_value, "new_value": c.new_value,
             "corrected_by": c.corrected_by, "note": c.note, "created_at": c.created_at.isoformat() if c.created_at else None}
            for c in inv.corrections
        ]
    return out
