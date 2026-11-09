"""Search over extracted invoice records.

  keyword   PostgreSQL full-text search (GIN index on a generated tsvector) plus
            trigram/ILIKE fallback for partial invoice numbers and names
  semantic  pgvector cosine distance on local bge-small embeddings
  hybrid    both lists fused with Reciprocal Rank Fusion (default)

All modes accept the same structured filters (status, supplier, date range,
amount range, currency, issue code, file type, document).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from ..models import Document, Invoice, ValidationIssue
from .embed import embed


@dataclass
class SearchFilters:
    review_status: str | None = None
    supplier: str | None = None
    customer: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    min_total: float | None = None
    max_total: float | None = None
    currency: str | None = None
    issue_code: str | None = None
    needs_review: bool | None = None
    file_type: str | None = None
    record_kind: str | None = None
    document_id: str | None = None


def _apply_filters(q: Select, f: SearchFilters) -> Select:
    if f.review_status:
        q = q.where(Invoice.review_status == f.review_status)
    if f.needs_review is not None:
        q = q.where(Invoice.needs_review.is_(f.needs_review))
    if f.supplier:
        q = q.where(Invoice.supplier_name.ilike(f"%{f.supplier}%"))
    if f.customer:
        q = q.where(Invoice.customer_name.ilike(f"%{f.customer}%"))
    if f.date_from:
        q = q.where(Invoice.invoice_date >= f.date_from)
    if f.date_to:
        q = q.where(Invoice.invoice_date <= f.date_to)
    if f.min_total is not None:
        q = q.where(Invoice.total >= f.min_total)
    if f.max_total is not None:
        q = q.where(Invoice.total <= f.max_total)
    if f.currency:
        q = q.where(Invoice.currency == f.currency.upper())
    if f.record_kind:
        q = q.where(Invoice.record_kind == f.record_kind)
    if f.file_type:
        q = q.where(Document.file_type == f.file_type)
    if f.document_id:
        q = q.where(Invoice.document_id == f.document_id)
    if f.issue_code:
        q = q.where(Invoice.id.in_(select(ValidationIssue.invoice_id).where(ValidationIssue.code == f.issue_code, ValidationIssue.resolved.is_(False))))
    return q


def _row(inv: Invoice, filename: str, score: float | None, snippet: str | None, file_type: str) -> dict:
    return {
        "id": str(inv.id),
        "document_id": str(inv.document_id),
        "filename": filename,
        "file_type": file_type,
        "record_kind": inv.record_kind,
        "invoice_number": inv.invoice_number,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "supplier_name": inv.supplier_name,
        "customer_name": inv.customer_name,
        "total": float(inv.total) if inv.total is not None else None,
        "currency": inv.currency,
        "review_status": inv.review_status,
        "needs_review": inv.needs_review,
        "confidence": inv.confidence,
        "page_start": inv.page_start,
        "sheet_name": inv.sheet_name,
        "row_index": inv.row_index,
        "score": round(score, 4) if score is not None else None,
        "snippet": snippet,
    }


def search(session: Session, q: str | None, mode: str = "hybrid", filters: SearchFilters | None = None,
           limit: int = 25, offset: int = 0) -> dict:
    f = filters or SearchFilters()
    q = (q or "").strip()
    base = select(Invoice, Document.filename, Document.file_type).join(Document)
    base = _apply_filters(base, f)

    if not q:
        total = session.scalar(select(func.count()).select_from(base.subquery()))
        rows = session.execute(base.order_by(Invoice.created_at.desc(), Invoice.position).limit(limit).offset(offset)).all()
        return {"mode": "browse", "total": total, "results": [_row(i, fn, None, None, ft) for i, fn, ft in rows]}

    keyword_hits: list[tuple] = []
    semantic_hits: list[tuple] = []
    pool = max(limit + offset, 50)

    if mode in ("keyword", "hybrid"):
        tsq = func.websearch_to_tsquery("simple", q)
        rank = func.ts_rank_cd(Invoice.search_tsv, tsq)
        snippet = func.ts_headline("simple", func.left(Invoice.search_text, 4000), tsq,
                                   "MaxWords=18, MinWords=6, StartSel=⟦, StopSel=⟧")
        # sentinel markers (not HTML): the UI escapes the text and renders the markers as <mark>
        like = f"%{q}%"
        kq = (
            base.add_columns(rank.label("rank"), snippet.label("snip"))
            .where(or_(Invoice.search_tsv.op("@@")(tsq), Invoice.invoice_number.ilike(like),
                       Invoice.supplier_name.ilike(like), Invoice.customer_name.ilike(like)))
            .order_by(rank.desc())
            .limit(pool)
        )
        keyword_hits = session.execute(kq).all()

    if mode in ("semantic", "hybrid"):
        vec = embed([q])
        if vec:
            dist = Invoice.embedding.cosine_distance(vec[0])
            sq = base.add_columns(dist.label("dist")).where(Invoice.embedding.is_not(None)).order_by(dist).limit(pool)
            semantic_hits = session.execute(sq).all()

    if mode == "keyword" or (mode == "hybrid" and not semantic_hits):
        res = [_row(i, fn, float(r or 0), sn, ft) for i, fn, ft, r, sn in keyword_hits]
    elif mode == "semantic":
        res = [_row(i, fn, 1 - float(d), None, ft) for i, fn, ft, d in semantic_hits]
    else:
        # Reciprocal Rank Fusion: robust to the two scores living on different scales
        k = 60
        scores: dict[str, float] = {}
        rows: dict[str, dict] = {}
        for rank_i, (i, fn, ft, _rank, sn) in enumerate(keyword_hits):
            key = str(i.id)
            scores[key] = scores.get(key, 0) + 1 / (k + rank_i + 1)
            rows[key] = _row(i, fn, None, sn, ft)
        for rank_i, (i, fn, ft, d) in enumerate(semantic_hits):
            key = str(i.id)
            # semantic-only results must be at least loosely related
            if key not in rows and float(d) > 0.55:
                continue
            scores[key] = scores.get(key, 0) + 1 / (k + rank_i + 1)
            rows.setdefault(key, _row(i, fn, None, None, ft))
        order = sorted(scores, key=scores.get, reverse=True)
        res = []
        for key in order:
            r = rows[key]
            r["score"] = round(scores[key] * 100, 3)
            res.append(r)
    return {"mode": mode, "total": len(res), "results": res[offset : offset + limit]}
