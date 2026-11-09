"""REST API: upload, background processing, persistence, search and corrections."""
from __future__ import annotations

import pytest

from tests.conftest import pdf_bytes, xlsx_bytes


def upload(client, *files):
    r = client.post("/api/documents", files=[("files", (n, d)) for n, d in files])
    assert r.status_code == 202, r.text
    return r.json()


def test_health_is_public(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["database"]["ok"]


def test_upload_process_status_results(client, invoice):
    res = upload(client, ("a.pdf", pdf_bytes(invoice)))
    doc = res["documents"][0]
    st = client.get(f"/api/documents/{doc['id']}/status").json()
    assert st["status"] in ("completed", "needs_review") and st["progress"] == 1.0
    out = client.get(f"/api/documents/{doc['id']}/results").json()
    r0 = out["records"][0]
    assert r0["invoice_number"] == invoice["invoice_number"]
    assert r0["total"] == pytest.approx(invoice["total"])
    assert r0["fields"]["total"]["source"]["box"]
    detail = client.get(f"/api/documents/{doc['id']}").json()
    assert {e["stage"] for e in detail["events"]} >= {"ingest", "extract", "validate", "index", "processing"}


def test_unsupported_types_are_rejected_at_upload(client):
    res = upload(client, ("notes.docx", b"hi"), ("ok.csv", b"Invoice No,Total\nA-1,5\n"))
    assert len(res["documents"]) == 1 and res["rejected"][0]["filename"] == "notes.docx"


def test_corrupted_file_fails_and_can_be_reprocessed(client):
    doc = upload(client, ("broken.pdf", b"%PDF-1.4 truncated"))["documents"][0]
    d = client.get(f"/api/documents/{doc['id']}").json()
    assert d["status"] == "failed" and d["error_code"] == "corrupted_file"
    r = client.post(f"/api/documents/{doc['id']}/reprocess")
    assert r.status_code == 200
    d = client.get(f"/api/documents/{doc['id']}").json()
    assert d["attempts"] == 2 and d["status"] == "failed"
    assert client.post("/api/documents/reprocess-failed").json()["requeued"] == [doc["id"]]


def test_reprocess_requires_force_for_successful_docs(client, invoice):
    doc = upload(client, ("a.pdf", pdf_bytes(invoice)))["documents"][0]
    assert client.post(f"/api/documents/{doc['id']}/reprocess").status_code == 409
    assert client.post(f"/api/documents/{doc['id']}/reprocess?force=true").status_code == 200


def test_duplicate_invoice_detected_across_documents(client, invoice):
    upload(client, ("a.pdf", pdf_bytes(invoice)))
    doc2 = upload(client, ("a-again.pdf", pdf_bytes(invoice, template=1)))["documents"][0]
    recs = client.get(f"/api/documents/{doc2['id']}/results").json()["records"]
    assert any(i["code"] == "duplicate_invoice" for i in recs[0]["issues"])
    assert recs[0]["needs_review"]


def test_ledger_cross_check_flags_differences(client, invoice):
    upload(client, ("inv.pdf", pdf_bytes(invoice)))
    ledger = xlsx_bytes({"AP": [["Invoice No", "Vendor", "Total"], [invoice["invoice_number"], invoice["supplier_name"], invoice["total"] + 100]]})
    doc = upload(client, ("ledger.xlsx", ledger))["documents"][0]
    rec = client.get(f"/api/documents/{doc['id']}/results").json()["records"][0]
    assert any(i["code"] == "ledger_mismatch" for i in rec["issues"])


def test_manual_correction_is_audited_and_revalidated(client, invoice):
    doc = upload(client, ("nonum.pdf", pdf_bytes(invoice, hide_number=True)))["documents"][0]
    rec = client.get(f"/api/documents/{doc['id']}/results").json()["records"][0]
    assert rec["needs_review"] and any(i["code"] == "missing_field" for i in rec["issues"])
    r = client.patch(f"/api/invoices/{rec['id']}", json={"fields": {"invoice_number": "HC-777"}, "reviewer": "rafi"})
    assert r.status_code == 200
    body = r.json()
    assert body["invoice_number"] == "HC-777" and body["fields"]["invoice_number"]["method"] == "manual"
    assert not any(i["code"] == "missing_field" and i["field"] == "invoice_number" for i in body["issues"])
    assert body["corrections"][0]["old_value"] == {"value": None}
    assert body["corrections"][0]["corrected_by"] == "Demo Admin"  # the signed-in user, not a client-supplied name


def test_correction_input_is_validated(client, invoice):
    doc = upload(client, ("a.pdf", pdf_bytes(invoice)))["documents"][0]
    rec = client.get(f"/api/documents/{doc['id']}/results").json()["records"][0]
    assert client.patch(f"/api/invoices/{rec['id']}", json={"fields": {"total": "lots"}}).status_code == 422
    assert client.patch(f"/api/invoices/{rec['id']}", json={"fields": {"hacker": 1}}).status_code == 422


def test_approve_clears_review_flag(client, invoice):
    doc = upload(client, ("nonum.pdf", pdf_bytes(invoice, hide_number=True)))["documents"][0]
    rec = client.get(f"/api/documents/{doc['id']}/results").json()["records"][0]
    body = client.post(f"/api/invoices/{rec['id']}/approve").json()
    assert body["review_status"] == "approved" and not body["needs_review"]
    assert client.get(f"/api/documents/{doc['id']}").json()["status"] == "completed"


def test_keyword_semantic_and_filtered_search(client, rng):
    from eval.generate_dataset import make_invoice

    invs = [make_invoice(rng, 300 + i) for i in range(3)]
    invs[0]["line_items"] = [{"description": "Wheelchair rental (monthly)", "quantity": 1.0, "unit_price": 80.0, "amount": 80.0}]
    invs[0].update(subtotal=80.0, tax=0.0, total=80.0)
    upload(client, *[(f"s{i}.pdf", pdf_bytes(inv)) for i, inv in enumerate(invs)])

    kw = client.get("/api/search", params={"q": invs[1]["invoice_number"], "mode": "keyword"}).json()
    assert kw["results"][0]["invoice_number"] == invs[1]["invoice_number"]
    sem = client.get("/api/search", params={"q": "mobility equipment hire", "mode": "semantic"}).json()
    assert sem["results"][0]["invoice_number"] == invs[0]["invoice_number"]
    flt = client.get("/api/search", params={"max_total": 81, "min_total": 79}).json()
    assert [r["invoice_number"] for r in flt["results"]] == [invs[0]["invoice_number"]]
    snippet = client.get("/api/search", params={"q": "wheelchair", "mode": "keyword"}).json()["results"][0]["snippet"]
    assert "<" not in snippet and "⟦" in snippet  # markers, never HTML


def test_compare_endpoint(client, invoice):
    a = upload(client, ("inv.pdf", pdf_bytes(invoice)))["documents"][0]
    led = xlsx_bytes({"AP": [["Invoice No", "Total"], [invoice["invoice_number"], invoice["total"]]]})
    b = upload(client, ("led.xlsx", led))["documents"][0]
    r = client.post("/api/compare", json={"left_document_id": a["id"], "right_document_id": b["id"]}).json()
    assert r["summary"]["matched"] == 1 and r["summary"]["fully_consistent"] == 1
    assert client.get("/api/compare").json()[0]["id"] == r["id"]


def test_page_image_and_file_download(client, invoice):
    doc = upload(client, ("a.pdf", pdf_bytes(invoice)))["documents"][0]
    img = client.get(f"/api/documents/{doc['id']}/pages/1/image")
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    assert client.get(f"/api/documents/{doc['id']}/pages/9/image").status_code == 404
    assert client.get(f"/api/documents/{doc['id']}/file").content[:4] == b"%PDF"


def test_filenames_are_sanitised(client):
    doc = upload(client, ("../../etc/passwd.csv", b"Invoice No,Total\nA,1\n"))["documents"][0]
    assert doc["filename"] == "passwd.csv"


def test_stats(client, invoice):
    upload(client, ("a.pdf", pdf_bytes(invoice)), ("b.pdf", b"junk"))
    s = client.get("/api/stats").json()
    assert s["documents"]["total"] == 2 and s["documents"]["by_status"]["failed"] == 1


def test_compare_many_invoices_against_one_ledger(client, rng):
    from eval.generate_dataset import make_invoice

    invs = [make_invoice(rng, 500 + i) for i in range(3)]
    docs = [upload(client, (f"i{i}.pdf", pdf_bytes(inv)))["documents"][0]["id"] for i, inv in enumerate(invs)]
    rows = [["Invoice No", "Total"]] + [[inv["invoice_number"], inv["total"]] for inv in invs]
    rows[2][1] = invs[1]["total"] + 9  # one ledger entry is wrong
    led = upload(client, ("led.xlsx", xlsx_bytes({"AP": rows})))["documents"][0]["id"]
    r = client.post("/api/compare", json={"left_document_ids": docs, "right_document_id": led}).json()
    assert r["summary"]["matched"] == 3 and r["summary"]["with_mismatches"] == 1
    assert r["left"]["count"] == 3


def test_late_ledger_updates_earlier_document_status(client, invoice):
    doc = upload(client, ("inv.pdf", pdf_bytes(invoice)))["documents"][0]
    first = client.get(f"/api/documents/{doc['id']}").json()["status"]
    led = xlsx_bytes({"AP": [["Invoice No", "Total"], [invoice["invoice_number"], invoice["total"] + 50]]})
    upload(client, ("ledger.xlsx", led))
    assert client.get(f"/api/documents/{doc['id']}").json()["status"] == "needs_review"
    assert first in ("completed", "needs_review")
