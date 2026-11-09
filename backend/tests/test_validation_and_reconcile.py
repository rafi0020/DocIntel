"""Validation rules, spreadsheet records and cross-verification."""
from __future__ import annotations

from datetime import date

import pytest

from app.extraction.schema import ExtractedInvoice, FieldValue, LineItem
from app.extraction.spreadsheet import extract_sheet
from app.pipeline.ingest import ingest
from app.validation.reconcile import amount_hint, reconcile
from app.validation.rules import needs_review, validate_record
from tests.conftest import xlsx_bytes


def rec(**vals):
    inv = ExtractedInvoice()
    base = dict(invoice_number="A-1", invoice_date="2026-05-01", supplier_name="Acme", customer_name="Care Co",
                subtotal=100.0, tax=10.0, total=110.0, currency="USD")
    base.update({k: v for k, v in vals.items() if k != "items"})
    for k, v in base.items():
        inv.fields[k] = FieldValue(value=v, confidence=0.95, method="llm+rules")
    inv.line_items = [LineItem(**i) for i in vals.get("items", [{"description": "x", "quantity": 2, "unit_price": 50, "amount": 100}])]
    return inv


def codes(issues):
    return {i.code for i in issues}


def test_clean_record_passes():
    issues = validate_record(rec(), today=date(2026, 6, 1))
    assert not needs_review(issues), issues


def test_total_mismatch_reports_the_difference():
    issues = validate_record(rec(total=101.1), today=date(2026, 6, 1))
    i = next(i for i in issues if i.code == "total_mismatch")
    assert i.severity == "error" and i.details["difference"] == pytest.approx(-8.9)


def test_line_items_vs_subtotal_and_line_arithmetic():
    issues = validate_record(rec(items=[{"description": "x", "quantity": 2, "unit_price": 50, "amount": 125}]), today=date(2026, 6, 1))
    assert {"line_items_mismatch", "line_item_arithmetic"} <= codes(issues)


def test_missing_required_vs_expected_fields():
    inv = rec()
    inv.fields["invoice_number"] = FieldValue()
    inv.fields["customer_name"] = FieldValue()
    issues = validate_record(inv, today=date(2026, 6, 1))
    sev = {(i.code, i.field): i.severity for i in issues}
    assert sev[("missing_field", "invoice_number")] == "error"
    assert sev[("missing_field", "customer_name")] == "warning"


def test_numeric_sanity_rules():
    assert "tax_exceeds_subtotal" in codes(validate_record(rec(tax=150.0, total=250.0), today=date(2026, 6, 1)))
    assert "unusual_tax_rate" in codes(validate_record(rec(tax=60.0, total=160.0), today=date(2026, 6, 1)))
    assert "non_positive_total" in codes(validate_record(rec(subtotal=0.0, tax=0.0, total=0.0, items=[]), today=date(2026, 6, 1)))
    assert "future_date" in codes(validate_record(rec(invoice_date="2027-01-01"), today=date(2026, 6, 1)))


def test_rounding_within_tolerance_is_accepted():
    assert "total_mismatch" not in codes(validate_record(rec(total=110.01), today=date(2026, 6, 1)))


def test_unverified_value_is_a_warning():
    inv = rec()
    inv.fields["customer_name"] = FieldValue(candidate="Invented Ltd")
    assert "unverified_value" in codes(validate_record(inv, today=date(2026, 6, 1)))


def test_ledger_sheet_rows_become_records_with_cell_provenance():
    data = xlsx_bytes({"AP": [["Accounts payable"], [], ["Invoice No", "Date", "Vendor", "Net Amount", "Tax", "Total", "Currency"],
                              ["A-1", "2026-01-05", "Acme", 100, 10, 110, "USD"], ["A-2", "2026-01-06", "Beta", "12x", 0, 50, "USD"],
                              ["Total", "", "", "", "", 160, ""]]})
    page = ingest(data, "l.xlsx").pages[0]
    recs = extract_sheet(page)
    assert [r.value("invoice_number") for r in recs] == ["A-1", "A-2"]
    assert recs[0].fields["total"].source == {"sheet": "AP", "row": 3, "col": 6}
    bad = validate_record(recs[1], today=date(2026, 6, 1))
    assert "invalid_number" in codes(bad)


def test_item_table_is_grouped_by_invoice_number():
    data = xlsx_bytes({"Lines": [["Invoice No", "Description", "Qty", "Unit Price", "Line Total"],
                                 ["A-1", "Visit", 2, 50, 100], ["", "Kit", 1, 20, 20], ["A-2", "Visit", 1, 50, 50]]})
    recs = extract_sheet(ingest(data, "i.xlsx").pages[0])
    assert len(recs) == 2 and len(recs[0].line_items) == 2


def test_reconcile_finds_mismatches_and_hints():
    left = [{"id": "d1", "invoice_number": "INV-1023", "total": 1250.0, "invoice_date": "2026-01-01", "supplier_name": "Acme"},
            {"id": "d2", "invoice_number": "INV-2000", "total": 50.0, "invoice_date": "2026-01-02", "supplier_name": "Acme"},
            {"id": "d3", "invoice_number": "INV-3000", "total": 75.0, "invoice_date": "2026-01-03", "supplier_name": "Beta"}]
    right = [{"id": "l1", "invoice_number": "inv 1023", "total": 1520.0, "invoice_date": "2026-01-01", "supplier_name": "ACME Inc."},
             {"id": "l2", "invoice_number": "INV-2O00", "total": 50.0, "invoice_date": "2026-01-02", "supplier_name": "Acme"},  # OCR O/0
             {"id": "l3", "invoice_number": "INV-9999", "total": 10.0, "invoice_date": "2026-01-09", "supplier_name": "Gamma"}]
    res = reconcile(left, right)
    s = res["summary"]
    assert s["matched"] == 2 and s["only_in_left"] == 1 and s["only_in_right"] == 1
    # both pairs differ: a transposed total, and an invoice number misread by OCR (0 vs O)
    assert s["with_mismatches"] == 2
    total_diff = next(f for f in res["pairs"][0]["fields"] if f["field"] == "total")
    assert total_diff["status"] == "mismatch" and "transposition" in total_diff["hint"]
    assert res["pairs"][1]["matched_by"] == "invoice_number_fuzzy"
    assert [f["field"] for f in res["pairs"][1]["fields"] if f["status"] == "mismatch"] == ["invoice_number"]


def test_amount_hints():
    assert "decimal" in amount_hint(120.5, 1205.0)
    assert "rounding" in amount_hint(10.0, 10.4)
    assert amount_hint(100.0, 250.0) is None


def test_same_invoice_on_two_sheets_is_merged_for_comparison():
    right = [{"id": "a", "document_id": "L", "sheet_name": "AP", "invoice_number": "A-1", "total": 10.0, "line_items": []},
             {"id": "b", "document_id": "L", "sheet_name": "Items", "invoice_number": "A-1", "total": None,
              "line_items": [{"description": "x", "amount": 10.0}]}]
    res = reconcile([{"id": "d", "invoice_number": "A-1", "total": 10.0}], right)
    assert res["summary"]["right_records"] == 1 and res["summary"]["only_in_right"] == 0


def test_exact_matches_win_over_fuzzy_regardless_of_order():
    left = [{"id": "c1", "invoice_number": "2026694006", "total": 10.0},
            {"id": "c2", "invoice_number": "2026694006", "total": 10.0},   # re-sent copy
            {"id": "r", "invoice_number": "2026694065", "total": 99.0}]
    right = [{"id": "L1", "invoice_number": "2026694006", "total": 10.0},
             {"id": "L2", "invoice_number": "2026694065", "total": 99.0}]
    res = reconcile(left, right)
    assert {(p["left_id"], p["right_id"]) for p in res["pairs"]} == {("c1", "L1"), ("r", "L2")}
    assert [x["id"] for x in res["only_left"]] == ["c2"]
