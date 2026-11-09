"""Export extracted records as CSV, XLSX or JSON (same filters as search)."""
from __future__ import annotations

import csv
import io
import json
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import Principal, audit, get_principal
from ..db import get_session
from ..models import Document, Invoice, ValidationIssue
from ..search.service import SearchFilters, _apply_filters

router = APIRouter(prefix="/api", tags=["export"])
MAX_ROWS = 50_000
COLUMNS = ["document", "record_kind", "invoice_number", "invoice_date", "supplier", "customer", "subtotal", "tax", "total", "currency",
           "review_status", "needs_review", "confidence", "open_issues", "line_items", "sheet", "row"]


def _safe(v):
    """Neutralise spreadsheet formulas (CSV/Excel injection) in text that came from a document."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


@router.get("/export", summary="Download records as CSV, XLSX or JSON (accepts the search filters)")
def export(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|json)$"),
    review_status: str | None = None, needs_review: bool | None = None, supplier: str | None = None, customer: str | None = None,
    date_from: date | None = None, date_to: date | None = None, min_total: float | None = None, max_total: float | None = None,
    currency: str | None = None, issue_code: str | None = None, file_type: str | None = None, record_kind: str | None = None,
    session: Session = Depends(get_session), principal: Principal = Depends(get_principal),
):
    f = SearchFilters(review_status, supplier, customer, date_from, date_to, min_total, max_total, currency, issue_code, needs_review,
                      file_type, record_kind, None)
    open_issues = (select(func.count()).select_from(ValidationIssue)
                   .where(ValidationIssue.invoice_id == Invoice.id, ValidationIssue.resolved.is_(False), ValidationIssue.severity != "info")
                   .scalar_subquery())
    stmt = _apply_filters(select(Invoice, Document.filename, open_issues).join(Document), f).order_by(Invoice.created_at.desc(), Invoice.position).limit(MAX_ROWS)
    rows = []
    for inv, filename, n_issues in session.execute(stmt).all():
        rows.append([filename, inv.record_kind, inv.invoice_number, inv.invoice_date.isoformat() if inv.invoice_date else None, inv.supplier_name,
                     inv.customer_name, float(inv.subtotal) if inv.subtotal is not None else None, float(inv.tax) if inv.tax is not None else None,
                     float(inv.total) if inv.total is not None else None, inv.currency, inv.review_status, inv.needs_review,
                     round(inv.confidence, 3) if inv.confidence is not None else None, n_issues, len(inv.line_items or []), inv.sheet_name, inv.row_index])
    audit(session, principal, "export.download", None, None, {"format": format, "rows": len(rows)}, request)
    session.commit()
    stamp = date.today().isoformat()
    if format == "json":
        body = json.dumps([dict(zip(COLUMNS, r, strict=True)) for r in rows], indent=1)
        return Response(body, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="docintel-{stamp}.json"'})
    safe = [[_safe(c) for c in r] for r in rows]
    if format == "xlsx":
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Records"
        ws.append(COLUMNS)
        for r in safe:
            ws.append(r)
        ws.freeze_panes = "A2"
        buf = io.BytesIO()
        wb.save(buf)
        return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="docintel-{stamp}.xlsx"'})
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(COLUMNS)
    w.writerows(safe)
    return Response("﻿" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="docintel-{stamp}.csv"'})
