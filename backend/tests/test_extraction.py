"""Extraction: accuracy on every template, provenance, LLM merge and fallback."""
from __future__ import annotations

import pytest

from app.extraction.extractor import extract_from_pages
from app.extraction.llm import LLMError, LLMResult
from app.pipeline.ingest import ingest
from app.pipeline.process import process_document
from app.pipeline.segment import split_invoices
from tests.conftest import pdf_bytes


class FakeLLM:
    """Stands in for a provider: returns a canned JSON answer (or fails)."""

    def __init__(self, data=None, fail=False):
        self.data, self.fail, self.name = data or {}, fail, "fake:model"
        self.calls = 0

    def extract(self, text):
        self.calls += 1
        if self.fail:
            raise LLMError("HTTP 503: overloaded")
        return LLMResult(self.data, self.name, 5, "{}")


def _truth_matches(inv, gt):
    v = inv.value
    assert v("invoice_number") == gt["invoice_number"]
    assert v("invoice_date") == gt["invoice_date"]
    assert v("total") == pytest.approx(gt["total"])
    assert v("subtotal") == pytest.approx(gt["subtotal"])
    assert v("tax") == pytest.approx(gt["tax"])
    assert v("currency") == gt["currency"]
    assert v("customer_name") == gt["customer_name"]


@pytest.mark.parametrize("template", [0, 1, 2, 3])
@pytest.mark.parametrize("date_fmt", ["iso", "long", "dmon"])
def test_rules_extract_every_template(invoice, template, date_fmt):
    out = process_document(pdf_bytes(invoice, template, date_fmt), "i.pdf", use_llm=False)
    assert len(out.records) == 1
    _truth_matches(out.records[0].invoice, invoice)
    items = out.records[0].invoice.line_items
    assert [round(i.amount, 2) for i in items] == [round(i["amount"], 2) for i in invoice["line_items"]]


def test_european_number_format(invoice):
    out = process_document(pdf_bytes(invoice, 1, "iso", "eu"), "eu.pdf", use_llm=False)
    assert out.records[0].invoice.value("total") == pytest.approx(invoice["total"])


def test_every_value_points_to_its_location(invoice):
    inv = process_document(pdf_bytes(invoice), "i.pdf", use_llm=False).records[0].invoice
    for name in ("invoice_number", "total", "invoice_date"):
        src = inv.fields[name].source
        assert src["page"] == 1 and len(src["box"]) == 4


def test_missing_values_stay_null_and_are_flagged(invoice):
    out = process_document(pdf_bytes(invoice, hide_number=True), "nonum.pdf", use_llm=False)
    rec = out.records[0]
    assert rec.invoice.value("invoice_number") is None
    assert any(i.code == "missing_field" and i.field == "invoice_number" for i in rec.issues)


def test_hallucinated_llm_values_are_rejected(invoice):
    pages = ingest(pdf_bytes(invoice), "i.pdf").pages
    llm = FakeLLM({
        "invoice_number": invoice["invoice_number"],
        "total": 999999.99,                       # not on the page
        "customer_name": "Totally Invented Corp",  # not on the page
        "currency": invoice["currency"],
    })
    inv = extract_from_pages(pages, llm)
    assert inv.value("total") == pytest.approx(invoice["total"])  # rules value, the LLM's was rejected
    assert inv.fields["total"].note is None  # the rejected LLM value is not even a "disagreement"
    assert inv.value("customer_name") == invoice["customer_name"]
    assert inv.fields["invoice_number"].confidence == 0.95  # LLM and rules agree


def test_llm_value_not_found_anywhere_becomes_null_with_candidate(invoice):
    invoice = {**invoice}
    pages = ingest(pdf_bytes(invoice, hide_number=True), "i.pdf").pages
    inv = extract_from_pages(pages, FakeLLM({"invoice_number": "INV-FAKE-0001"}))
    f = inv.fields["invoice_number"]
    assert f.value is None and f.candidate == "INV-FAKE-0001"


def test_llm_failure_falls_back_to_rules(invoice):
    pages = ingest(pdf_bytes(invoice), "i.pdf").pages
    inv = extract_from_pages(pages, FakeLLM(fail=True))
    assert inv.value("total") == pytest.approx(invoice["total"])
    assert inv.extractor == "rules" and "LLM extraction failed" in inv.notes[0]


def test_llm_line_items_are_verified(invoice):
    pages = ingest(pdf_bytes(invoice), "i.pdf").pages
    real = invoice["line_items"][0]
    inv = extract_from_pages(pages, FakeLLM({"line_items": [
        real,
        {"description": "Gold-plated stethoscope", "quantity": 1, "unit_price": 12345.67, "amount": 12345.67},
    ]}))
    assert len(inv.line_items) == 1 and inv.line_items[0].amount == pytest.approx(real["amount"])


def test_batch_pdf_is_split_into_invoices(rng):
    import pymupdf

    from eval.generate_dataset import make_invoice

    batch = pymupdf.open()
    truth = []
    for k in range(6):
        inv = make_invoice(rng, 900 + k)
        if k == 2:
            inv["line_items"] = inv["line_items"] * 8  # a multi-page invoice in the middle
        truth.append(inv)
        batch.insert_pdf(pymupdf.open(stream=pdf_bytes(inv, k % 4), filetype="pdf"))
    pages = ingest(batch.tobytes(), "batch.pdf").pages
    segs = split_invoices(pages)
    assert len(segs) == 6
    out = process_document(batch.tobytes(), "batch.pdf", use_llm=False)
    assert [r.invoice.value("invoice_number") for r in out.records] == [t["invoice_number"] for t in truth]
