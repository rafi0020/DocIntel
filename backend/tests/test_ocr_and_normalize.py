"""OCR robustness and value normalisation."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import cv2
import numpy as np
import pytest

from app.extraction.normalize import (
    detect_currency,
    find_dates,
    norm_invoice_number,
    norm_name,
    parse_amount,
    parse_date,
)
from app.pipeline.ocr import ocr_image, preprocess, words_to_text
from tests.conftest import scan_png


def _decode(b: bytes):
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)


@pytest.mark.parametrize("quality", ["clean", "medium", "poor"])
def test_ocr_reads_totals_on_degraded_scans(invoice, quality):
    words, conf = ocr_image(_decode(scan_png(invoice, quality, template=0)))
    text = words_to_text(words)
    total = parse_amount(invoice["total"])
    from app.extraction.normalize import find_amounts

    found = [a for a, _, _ in find_amounts(text)]
    assert total in found, f"total {total} not read on {quality} scan"
    assert conf is not None and conf > 0.5


def test_preprocess_deskews_and_upscales():
    img = np.full((500, 400, 3), 255, np.uint8)
    cv2.putText(img, "TOTAL 123.45", (20, 250), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    out = preprocess(img)
    assert out.shape[1] >= 1200  # small images are upscaled for the recogniser


def test_ocr_boxes_are_normalised_and_in_reading_order(invoice):
    words, _ = ocr_image(_decode(scan_png(invoice, "clean")))
    assert all(0 <= v <= 1.0001 for w in words for v in w.box)
    lines = [w.line for w in words]
    assert lines == sorted(lines)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,234.56", "1234.56"), ("1.234,56", "1234.56"), ("$ 1 234,56", "1234.56"), ("(45.00)", "-45.00"),
        ("Tk 388.110,59", "388110.59"), ("12,50", "12.50"), ("337.487.47", "337487.47"), ("€0.60", "0.60"),
        ("1,000", "1000.00"), ("abc", None), ("", None),
    ],
)
def test_parse_amount(raw, expected):
    v = parse_amount(raw)
    assert (str(v) if v is not None else None) == expected


def test_dates_and_ambiguity():
    assert parse_date("2026-03-04")[0] == date(2026, 3, 4)
    assert parse_date("March 4, 2026")[0] == date(2026, 3, 4)
    assert parse_date("04-Mar-2026")[0] == date(2026, 3, 4)
    assert parse_date("25/03/2026")[0] == date(2026, 3, 25)  # unambiguous day-first
    d, amb = parse_date("03/04/2026", "MDY")
    assert d == date(2026, 3, 4) and amb
    assert parse_date("03/04/2026", "DMY")[0] == date(2026, 4, 3)
    assert not find_dates("Total 1,234.56")


def test_currency_and_name_normalisation():
    assert detect_currency("Amount Due Tk 5,000")[0] == "BDT"
    assert detect_currency("Total EUR 12.00")[0] == "EUR"
    assert detect_currency("no money here")[0] is None
    assert norm_invoice_number("inv - 2026/0012") == "INV20260012"
    assert norm_name("CarePoint Staffing Solutions LLC") == norm_name("Carepoint staffing solutions")
    assert parse_amount(Decimal("1.005")) == Decimal("1.01")


def test_ocr_split_decimal_is_repaired_only_with_thousands_group():
    from app.extraction.normalize import find_amounts

    vals = lambda t: [str(a[0]) for a in find_amounts(t)]  # noqa: E731
    assert vals("Subtotal   Tk 367.571 62") == ["367571.62"]
    assert vals("care   10   25,549.96   255.499 60")[-1] == "255499.60"
    assert vals("Qty 12 45.00") == ["12.00", "45.00"]  # never glue a quantity to a price
