"""Background job: process one document and persist everything.

Runs inside an RQ worker (or inline when QUEUE_SYNC=true). Deterministic file
problems (corrupted, encrypted, empty) fail immediately with a clear code;
unexpected errors are re-raised so RQ retries them with back-off, and the
document stays visible as failed with the error until a retry succeeds or a
user re-processes it.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import delete

from ..db import session_scope
from ..extraction.normalize import norm_invoice_number, norm_name
from ..extraction.schema import ExtractedInvoice
from ..models import Document, Invoice, Page, ProcessingEvent, ValidationIssue
from ..pipeline.doc_types import IngestError
from ..pipeline.process import process_document
from ..search.embed import embed, invoice_search_text
from ..validation.cross import run_cross_checks
from ..validation.rules import needs_review

log = logging.getLogger(__name__)


def _now():
    return datetime.now(UTC)


def _event(session, doc_id, attempt, stage, status, message=None, ms=None):
    session.add(ProcessingEvent(document_id=doc_id, attempt=attempt, stage=stage, status=status, message=message, duration_ms=ms))


def apply_extraction(inv_row: Invoice, ex: ExtractedInvoice) -> None:
    """Copy an ExtractedInvoice into the ORM row (fields JSON + flat columns)."""
    v = ex.value
    inv_row.fields = {k: f.model_dump() for k, f in ex.fields.items()}
    inv_row.line_items = [li.model_dump() for li in ex.line_items]
    inv_row.invoice_number = v("invoice_number")
    inv_row.invoice_number_norm = norm_invoice_number(v("invoice_number"))
    d = v("invoice_date")
    inv_row.invoice_date = date.fromisoformat(d) if d else None
    inv_row.supplier_name = v("supplier_name")
    inv_row.supplier_norm = norm_name(v("supplier_name"))
    inv_row.customer_name = v("customer_name")
    inv_row.subtotal = v("subtotal")
    inv_row.tax = v("tax")
    inv_row.total = v("total")
    inv_row.currency = v("currency")
    confs = [f.confidence for f in ex.fields.values() if f.value is not None]
    inv_row.confidence = round(sum(confs) / len(confs), 3) if confs else 0.0


def process_document_job(document_id: str) -> dict:
    doc_id = uuid.UUID(str(document_id))
    with session_scope() as session:
        doc = session.get(Document, doc_id)
        if doc is None:
            return {"status": "missing"}
        doc.status, doc.stage, doc.progress = "processing", "starting", 0.02
        doc.attempts = (doc.attempts or 0) + 1
        doc.started_at, doc.error_code, doc.error_message = _now(), None, None
        attempt, path, filename = doc.attempts, doc.storage_path, doc.filename
        _event(session, doc_id, attempt, "processing", "started")

    last = [0.0]

    def progress(frac: float, stage: str):
        if time.monotonic() - last[0] < 0.5 and frac < 0.99:
            return
        last[0] = time.monotonic()
        with session_scope() as ss:
            d = ss.get(Document, doc_id)
            if d is not None:
                d.progress, d.stage = round(min(0.97, frac), 3), stage

    t0 = time.perf_counter()
    try:
        data = Path(path).read_bytes()
        out = process_document(data, filename, progress)
    except IngestError as e:
        with session_scope() as session:
            doc = session.get(Document, doc_id)
            doc.status, doc.stage, doc.progress = "failed", "failed", 1.0
            doc.error_code, doc.error_message = e.code, e.message
            doc.finished_at = _now()
            doc.processing_ms = int((time.perf_counter() - t0) * 1000)
            _event(session, doc_id, attempt, "ingest", "error", f"{e.code}: {e.message}", doc.processing_ms)
        return {"status": "failed", "error_code": e.code}
    except Exception as e:
        log.exception("processing crashed for %s", doc_id)
        with session_scope() as session:
            doc = session.get(Document, doc_id)
            doc.status, doc.stage = "failed", "failed"
            doc.error_code, doc.error_message = "internal_error", f"{type(e).__name__}: {e}"
            doc.finished_at = _now()
            _event(session, doc_id, attempt, "processing", "error", f"{type(e).__name__}: {e}")
        raise  # let RQ retry transient failures

    # ------------------------------------------------------------ persist
    with session_scope() as session:
        doc = session.get(Document, doc_id)
        doc.stage, doc.progress = "saving", 0.97
        session.execute(delete(Page).where(Page.document_id == doc_id))
        session.execute(delete(Invoice).where(Invoice.document_id == doc_id))
        session.flush()
        ing = out.ingest
        doc.source_kind, doc.page_count = ing.source_kind, len(ing.pages)
        doc.full_text = ing.full_text[:2_000_000]
        for p in ing.pages:
            session.add(Page(document_id=doc_id, page_no=p.page_no, label=p.label, method=p.method,
                             ocr_confidence=p.ocr_confidence, width=p.width, height=p.height,
                             text=p.text, layout=p.layout_json(), error=p.error))
        for w in ing.warnings:
            _event(session, doc_id, attempt, "ingest", "warning", w)

        rows: list[Invoice] = []
        sem_texts: list[str] = []
        for pos, rec in enumerate(out.records):
            ex = rec.invoice
            row = Invoice(document_id=doc_id, position=pos, record_kind=ex.record_kind, page_start=ex.page_start,
                          page_end=ex.page_end, sheet_name=ex.sheet_name, row_index=ex.row_index,
                          raw_text=ex.raw_text[:200_000], extractor=ex.extractor)
            apply_extraction(row, ex)
            kw, sem = invoice_search_text(row.fields, row.line_items, ex.raw_text, filename)
            row.search_text = kw
            sem_texts.append(sem)
            issues = [i.to_dict() for i in rec.issues]
            row.needs_review = needs_review(issues)
            row.review_status = "needs_review" if row.needs_review else "auto_approved"
            session.add(row)
            session.flush()
            for i in issues:
                session.add(ValidationIssue(invoice_id=row.id, code=i["code"], severity=i["severity"],
                                            field=i["field"], message=i["message"], details=i["details"]))
            rows.append(row)

        t_emb = time.perf_counter()
        vecs = embed(sem_texts) if sem_texts else None
        if vecs:
            for row, v in zip(rows, vecs, strict=False):
                row.embedding = v
        emb_ms = int((time.perf_counter() - t_emb) * 1000)
        session.flush()
        session.refresh(doc)

        t_cross = time.perf_counter()
        run_cross_checks(session, doc)
        cross_ms = int((time.perf_counter() - t_cross) * 1000)

        for stage in ("ingest", "extract", "validate"):
            _event(session, doc_id, attempt, stage, "ok", None, out.timings_ms.get(stage))
        _event(session, doc_id, attempt, "index", "ok", f"{len(rows)} records embedded" if vecs else "keyword index only", emb_ms)
        _event(session, doc_id, attempt, "cross_checks", "ok", None, cross_ms)

        session.flush()
        session.refresh(doc)
        doc.invoice_count = len(rows)
        doc.extractor = out.extractor
        doc.status = "needs_review" if any(r.needs_review for r in doc.invoices) else "completed"
        doc.stage, doc.progress = "done", 1.0
        doc.finished_at = _now()
        doc.processing_ms = int((time.perf_counter() - t0) * 1000)
        _event(session, doc_id, attempt, "processing", "ok",
               f"{len(rows)} record(s), {sum(r.needs_review for r in rows)} need review", doc.processing_ms)
        return {"status": doc.status, "records": len(rows)}
