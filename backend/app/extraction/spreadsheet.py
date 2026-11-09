"""Turn spreadsheet sheets into invoice records.

Two layouts are recognised from the header row:
  * ledger      one row per invoice (number, date, supplier, total, ...)
  * item table  one row per line item, grouped into invoices by invoice number
A sheet with no recognisable header (e.g. an invoice laid out as a form in
Excel) falls back to text extraction like a PDF page.
Every value keeps its cell address as provenance.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from ..config import get_settings
from ..pipeline.doc_types import PageContent
from .normalize import parse_amount, parse_date
from .schema import AMOUNT_FIELDS, ExtractedInvoice, FieldValue, LineItem

SYNONYMS: dict[str, list[str]] = {
    "invoice_number": ["invoice number", "invoice no", "invoice #", "inv no", "invoice", "invoice id", "bill no", "inv #", "invoice ref", "doc no"],
    "invoice_date": ["invoice date", "date", "bill date", "issue date", "inv date", "document date"],
    "supplier_name": ["supplier", "vendor", "supplier name", "vendor name", "seller", "payee", "provider", "agency"],
    "customer_name": ["customer", "client", "customer name", "client name", "bill to", "buyer", "payer"],
    "subtotal": ["subtotal", "sub total", "net amount", "net", "amount before tax", "net total"],
    "tax": ["tax", "vat", "gst", "tax amount", "vat amount", "sales tax"],
    "total": ["total", "total amount", "grand total", "invoice total", "gross", "amount due", "gross amount", "invoice amount"],
    "currency": ["currency", "ccy", "cur", "curr"],
    "description": ["description", "item", "service", "item description", "particulars", "details"],
    "quantity": ["qty", "quantity", "hours", "units", "visits"],
    "unit_price": ["unit price", "rate", "price", "unit cost", "hourly rate", "rate per hour"],
    "line_amount": ["line total", "line amount", "amount", "ext price", "extended", "line value"],
}


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9# ]", " ", h.lower()).strip()


def _map_header(row: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    scores: dict[str, float] = {}
    for col, raw in enumerate(row):
        h = " ".join(_norm_header(raw).split())
        if not h or len(h) > 40:
            continue
        for field, syns in SYNONYMS.items():
            score = max(100 if h == s else fuzz.ratio(h, s) for s in syns)
            if score >= 85 and score > scores.get(field, 0) and col not in mapping.values():
                mapping[field], scores[field] = col, score
    return mapping


def _find_header(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    for i, row in enumerate(rows[:15]):
        m = _map_header(row)
        keys = set(m)
        if len(keys) >= 2 and keys & {"invoice_number", "total", "line_amount", "description"}:
            return i, m
    return None


def _fv(field: str, raw: str, sheet: str, row: int, col: int, order: str) -> FieldValue:
    if raw is None or str(raw).strip() == "":
        return FieldValue()
    src = {"sheet": sheet, "row": row, "col": col}
    if field in AMOUNT_FIELDS:
        # cells are typed data: be strict (a stray letter means a bad entry, not OCR noise)
        stripped = re.sub(r"\b[A-Z]{3}\b|[$€£৳₹¥]", "", str(raw))
        a = None if re.search(r"[A-Za-z]", stripped) else parse_amount(raw)
        if a is None:
            return FieldValue(value=None, candidate=raw, note=f"Cell value '{raw}' is not a valid number.", source=src)
        return FieldValue(value=float(a), confidence=0.97, source=src, method="ledger")
    if field == "invoice_date":
        d, amb = parse_date(raw, order)
        if d is None:
            return FieldValue(value=None, candidate=raw, note=f"Cell value '{raw}' is not a valid date.", source=src)
        return FieldValue(value=d.isoformat(), confidence=0.7 if amb else 0.97, source=src, method="ledger",
                          note=f"Day/month order is ambiguous; read as {order}." if amb else None)
    if field == "currency":
        v = str(raw).strip().upper()
        return FieldValue(value=v if len(v) == 3 else None, confidence=0.97, source=src, method="ledger", candidate=None if len(v) == 3 else raw)
    return FieldValue(value=" ".join(str(raw).split()), confidence=0.97, source=src, method="ledger")


def extract_sheet(page: PageContent) -> list[ExtractedInvoice] | None:
    """Return records for a tabular sheet, or None if the sheet isn't tabular."""
    rows = page.table or []
    found = _find_header(rows)
    if not found:
        return None
    hdr_idx, cols = found
    order = get_settings().ambiguous_date_order
    sheet = page.label or f"sheet{page.page_no}"
    header_fields = [f for f in ("invoice_number", "invoice_date", "supplier_name", "customer_name", "subtotal", "tax", "total", "currency") if f in cols]
    has_items = "description" in cols and ("line_amount" in cols or "unit_price" in cols)
    # In a ledger without item columns, a lone "amount" column is the invoice total.
    if not has_items and "total" not in cols and "line_amount" in cols:
        cols["total"] = cols.pop("line_amount")
        header_fields.append("total")

    def cell(r: list[str], key: str) -> str:
        c = cols.get(key)
        return r[c] if c is not None and c < len(r) else ""

    records: list[ExtractedInvoice] = []
    data_rows = [(hdr_idx + 1 + k, r) for k, r in enumerate(rows[hdr_idx + 1 :])]

    if not has_items:
        for excel_row, r in data_rows:
            if not any(cell(r, f) for f in header_fields):
                continue
            # skip footer totals rows ("Total", "", "", 12345)
            if re.match(r"(?i)^\s*(grand\s+|sub\s*)?(total|sum)\b", cell(r, "invoice_number") or " ".join(r).strip()):
                continue
            inv = ExtractedInvoice(record_kind="ledger_row", sheet_name=sheet, row_index=excel_row + 1, extractor="spreadsheet")
            for f in header_fields:
                inv.fields[f] = _fv(f, cell(r, f), sheet, excel_row + 1, cols[f] + 1, order)
            inv.raw_text = "   ".join(c for c in r if c)
            records.append(inv)
        return records

    # Item table: group consecutive rows by invoice number (forward-filled).
    current: ExtractedInvoice | None = None
    current_key = None
    for excel_row, r in data_rows:
        key = cell(r, "invoice_number") or current_key
        if not any(r):
            continue
        if re.match(r"(?i)^\s*(sub\s*total|total|tax|vat)", cell(r, "description") or ""):
            continue
        if current is None or key != current_key:
            current = ExtractedInvoice(record_kind="ledger_row", sheet_name=sheet, row_index=excel_row + 1, extractor="spreadsheet")
            for f in header_fields:
                current.fields[f] = _fv(f, cell(r, f), sheet, excel_row + 1, cols[f] + 1, order)
            current_key = key
            records.append(current)
        else:
            for f in header_fields:  # fill header fields that only appear on later rows
                if current.fields[f].value is None and cell(r, f):
                    current.fields[f] = _fv(f, cell(r, f), sheet, excel_row + 1, cols[f] + 1, order)
        q, u, a = (parse_amount(cell(r, k)) for k in ("quantity", "unit_price", "line_amount"))
        current.line_items.append(LineItem(
            description=cell(r, "description") or None,
            quantity=float(q) if q is not None else None,
            unit_price=float(u) if u is not None else None,
            amount=float(a) if a is not None else None,
            confidence=0.97,
            source={"sheet": sheet, "row": excel_row + 1, "col": (cols.get("line_amount", cols["description"])) + 1},
        ))
        current.raw_text += "   ".join(c for c in r if c) + "\n"
    return records
