"""Structured output contract for one invoice.

Every field carries its value *and* how much to trust it: a confidence score,
where on the page it was found (`source`), which extractor produced it and an
optional note. A value that could not be verified against the document text is
returned as null with the rejected candidate kept in `candidate` - the system
never fills a field with a value it cannot point to.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

FIELDS = [
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "subtotal",
    "tax",
    "total",
    "currency",
]
AMOUNT_FIELDS = {"subtotal", "tax", "total"}
REQUIRED_FIELDS = ["invoice_number", "invoice_date", "supplier_name", "total"]


class FieldValue(BaseModel):
    value: Any = None
    confidence: float = 0.0
    source: dict | None = None  # {"page": 1, "box": [x0,y0,x1,y1]} or {"sheet": "...", "row": 3, "col": 2}
    method: str | None = None  # rules | llm | llm+rules | ledger | manual
    note: str | None = None
    candidate: Any = None  # value proposed by an extractor but rejected (not found in document)


class LineItem(BaseModel):
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None
    confidence: float = 0.0
    source: dict | None = None


class ExtractedInvoice(BaseModel):
    fields: dict[str, FieldValue] = Field(default_factory=lambda: {f: FieldValue() for f in FIELDS})
    line_items: list[LineItem] = Field(default_factory=list)
    record_kind: str = "document"
    page_start: int | None = None
    page_end: int | None = None
    sheet_name: str | None = None
    row_index: int | None = None
    raw_text: str = ""
    extractor: str = "rules"
    notes: list[str] = Field(default_factory=list)

    def value(self, name: str):
        f = self.fields.get(name)
        return f.value if f else None

    def to_output_json(self) -> dict:
        """The clean JSON shape requested by the assignment."""
        out = {f: self.value(f) for f in FIELDS}
        out["line_items"] = [
            {k: getattr(li, k) for k in ("description", "quantity", "unit_price", "amount")} for li in self.line_items
        ]
        out["_meta"] = {
            f: {"confidence": round(self.fields[f].confidence, 3), "source": self.fields[f].source, "method": self.fields[f].method}
            for f in FIELDS
        }
        return out


# JSON schema handed to the LLM (kept deliberately small and explicit).
LLM_OUTPUT_SCHEMA = {
    "invoice_number": "string|null",
    "invoice_date": "string|null  (copy exactly as printed)",
    "supplier_name": "string|null  (the party issuing the invoice)",
    "customer_name": "string|null  (the party being billed)",
    "subtotal": "number|null",
    "tax": "number|null  (total tax/VAT/GST amount, not the rate)",
    "total": "number|null  (final amount payable)",
    "currency": "string|null  (ISO 4217 code ONLY if a code or symbol is printed)",
    "line_items": [{"description": "string", "quantity": "number|null", "unit_price": "number|null", "amount": "number|null"}],
    "evidence": {"<field>": "short verbatim text copied from the document that contains the value"},
}
