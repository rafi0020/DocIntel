"""Document processing: every format, multi-page and multi-sheet input, and bad input."""
from __future__ import annotations

import io

import numpy as np
import pytest

from app.pipeline.doc_types import IngestError
from app.pipeline.ingest import ingest, sniff_type
from tests.conftest import pdf_bytes, scan_pdf, scan_png, xlsx_bytes


def test_digital_pdf_uses_text_layer_with_word_boxes(invoice):
    res = ingest(pdf_bytes(invoice), "a.pdf")
    assert res.source_kind == "digital_pdf"
    p = res.pages[0]
    assert p.method == "text"
    assert invoice["invoice_number"] in p.text
    assert all(0 <= v <= 1 for w in p.words for v in w.box)


def test_multi_page_pdf_keeps_every_page(invoice):
    invoice["line_items"] = invoice["line_items"] * 6  # forces 2+ pages
    res = ingest(pdf_bytes(invoice), "long.pdf")
    assert len(res.pages) >= 2
    assert "Page 2 of" in res.pages[1].text


def test_scanned_pdf_falls_back_to_ocr(invoice):
    res = ingest(scan_pdf(invoice), "scan.pdf")
    assert res.source_kind == "scanned_pdf"
    assert res.pages[0].method == "ocr"
    assert res.pages[0].ocr_confidence and res.pages[0].ocr_confidence > 0.6
    assert invoice["supplier_name"].split()[0] in res.pages[0].text


def test_mixed_pdf_only_ocrs_pages_without_text(invoice):
    import pymupdf

    digital = pymupdf.open(stream=pdf_bytes(invoice), filetype="pdf")
    scanned = pymupdf.open(stream=scan_pdf(invoice), filetype="pdf")
    digital.insert_pdf(scanned)
    res = ingest(digital.tobytes(), "mixed.pdf")
    assert res.source_kind == "mixed_pdf"
    assert [p.method for p in res.pages] == ["text", "ocr"]


@pytest.mark.parametrize("ext", ["png", "jpg"])
def test_images_are_ocrd(invoice, ext):
    import cv2

    img = cv2.imdecode(np.frombuffer(scan_png(invoice, "clean"), np.uint8), cv2.IMREAD_COLOR)
    data = cv2.imencode(f".{ext}", img)[1].tobytes()
    res = ingest(data, f"x.{ext}")
    assert res.source_kind == "image" and res.pages[0].method == "ocr"
    assert len(res.pages[0].words) > 10


def test_multi_frame_tiff_becomes_multiple_pages(invoice):
    from PIL import Image

    im = Image.open(io.BytesIO(scan_png(invoice, "clean")))
    b = io.BytesIO()
    im.save(b, format="TIFF", save_all=True, append_images=[im.copy()])
    res = ingest(b.getvalue(), "two.tiff")
    assert len(res.pages) == 2


def test_xlsx_multiple_sheets_and_empty_sheet_warning():
    data = xlsx_bytes({"Ledger": [["Invoice No", "Total"], ["A-1", 10.5]], "Empty": [], "Notes": [["hello"]]})
    res = ingest(data, "book.xlsx")
    assert [p.label for p in res.pages] == ["Ledger", "Notes"]
    assert res.pages[0].table[1] == ["A-1", "10.5"]
    assert any("Empty" in w for w in res.warnings)


def test_xls_is_parsed():
    import xlwt

    wb = xlwt.Workbook()
    ws = wb.add_sheet("S")
    for i, row in enumerate([["Invoice No", "Total"], ["X-9", 99.0]]):
        for j, v in enumerate(row):
            ws.write(i, j, v)
    b = io.BytesIO()
    wb.save(b)
    res = ingest(b.getvalue(), "old.xls")
    assert res.file_type == "xls" and res.pages[0].table[1] == ["X-9", "99"]


def test_csv_with_semicolons_and_bom():
    data = "﻿Invoice No;Total;Vendor\nA-1;1.234,50;Acme\n".encode()
    res = ingest(data, "l.csv")
    assert res.pages[0].table[1] == ["A-1", "1.234,50", "Acme"]


@pytest.mark.parametrize(
    "name,data,code",
    [
        ("empty.pdf", b"", "empty_file"),
        ("random.pdf", bytes(range(256)) * 10, "corrupted_file"),
        ("header.pdf", b"%PDF-1.7\n", "corrupted_file"),
        ("bad.xlsx", b"PK\x03\x04garbage-garbage", "corrupted_file"),
        ("trunc.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 50, "corrupted_file"),
        ("notes.docx", b"hello", "unsupported_type"),
    ],
)
def test_corrupted_and_unsupported_files_fail_with_clear_codes(name, data, code):
    with pytest.raises(IngestError) as e:
        ingest(data, name)
    assert e.value.code == code


def test_blank_scan_reports_no_text():
    import cv2

    blank = cv2.imencode(".png", np.full((900, 700, 3), 255, np.uint8))[1].tobytes()
    with pytest.raises(IngestError) as e:
        ingest(blank, "blank.png")
    assert e.value.code == "no_text_found"


def test_encrypted_pdf_is_rejected(invoice):
    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes(invoice), filetype="pdf")
    enc = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="o")
    with pytest.raises(IngestError) as e:
        ingest(enc, "locked.pdf")
    assert e.value.code == "encrypted_pdf"


def test_type_is_sniffed_from_content_not_extension(invoice):
    assert sniff_type(pdf_bytes(invoice), "invoice.png") == "pdf"
