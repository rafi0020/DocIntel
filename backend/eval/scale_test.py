"""Scale test: time large multi-invoice PDFs through the real pipeline.

  * a ~1000-page digital PDF (hundreds of invoices of 1-3 pages)
  * a scanned (image-only) batch, to measure OCR throughput per page

Reports pages/second, invoices found vs. expected (splitting accuracy), field
accuracy on the batch and peak memory.

Usage: python -m eval.scale_test --pages 1000 --scan-pages 100 --out ../eval_results/scale
"""
from __future__ import annotations

import argparse
import json
import random
import resource
import time
from pathlib import Path

import pymupdf

from app.extraction.normalize import norm_invoice_number
from app.pipeline.process import process_document
from eval.generate_dataset import (
    degrade,
    images_to_pdf,
    make_invoice,
    pdf_to_images,
    render_pdf,
)


def build_batch(target_pages: int, seed: int) -> tuple[bytes, list[dict]]:
    rng = random.Random(seed)
    doc, truth, k = pymupdf.open(), [], 0
    while doc.page_count < target_pages:
        inv = make_invoice(rng, 70_000 + k)
        k += 1
        pdf = render_pdf(inv, rng.randrange(4), rng.choice(["iso", "mdy", "long", "dmon"]), "us")
        sub = pymupdf.open(stream=pdf, filetype="pdf")
        if doc.page_count + sub.page_count > target_pages:
            break
        doc.insert_pdf(sub)
        truth.append(inv)
    return doc.tobytes(garbage=3, deflate=True), truth


def score(out, truth):
    found = {norm_invoice_number(r.invoice.value("invoice_number")): r.invoice for r in out.records}
    hits = total = 0
    for t in truth:
        inv = found.get(norm_invoice_number(t["invoice_number"]))
        for f in ("invoice_number", "invoice_date", "total", "subtotal", "tax", "currency", "customer_name"):
            total += 1
            if inv is None:
                continue
            v = inv.value(f)
            hits += (abs(v - t[f]) < 0.011) if isinstance(t[f], float) and v is not None else (v == t[f])
    return round(100 * hits / total, 2), sum(1 for t in truth if norm_invoice_number(t["invoice_number"]) in found)


def run(pages: int, scan_pages: int, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    data, truth = build_batch(pages, 11)
    t0 = time.perf_counter()
    out = process_document(data, "batch_1000.pdf")
    secs = time.perf_counter() - t0
    acc, found = score(out, truth)
    results["digital_batch"] = {
        "pages": len(out.ingest.pages), "file_mb": round(len(data) / 1e6, 2), "invoices_expected": len(truth),
        "invoices_found": len(out.records), "invoices_matched": found, "field_accuracy_pct": acc,
        "seconds": round(secs, 2), "pages_per_second": round(len(out.ingest.pages) / secs, 1),
        "stage_ms": out.timings_ms, "extractor": out.extractor,
    }
    print(json.dumps(results["digital_batch"], indent=1), flush=True)

    if scan_pages:
        rng = random.Random(5)
        sdata, struth = build_batch(scan_pages, 12)
        imgs = [degrade(im, rng.choice(["clean", "medium"]), rng) for im in pdf_to_images(sdata)]
        scanned = images_to_pdf(imgs)
        t0 = time.perf_counter()
        out = process_document(scanned, "batch_scanned.pdf")
        secs = time.perf_counter() - t0
        acc, found = score(out, struth)
        results["scanned_batch"] = {
            "pages": len(out.ingest.pages), "file_mb": round(len(scanned) / 1e6, 2), "invoices_expected": len(struth),
            "invoices_found": len(out.records), "invoices_matched": found, "field_accuracy_pct": acc,
            "seconds": round(secs, 2), "seconds_per_page": round(secs / len(out.ingest.pages), 3),
            "stage_ms": out.timings_ms, "extractor": out.extractor,
        }
        print(json.dumps(results["scanned_batch"], indent=1), flush=True)

    results["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    (out_dir / "scale.json").write_text(json.dumps(results, indent=1))
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1000)
    ap.add_argument("--scan-pages", type=int, default=100)
    ap.add_argument("--out", default="../eval_results/scale")
    a = ap.parse_args()
    print(json.dumps(run(a.pages, a.scan_pages, Path(a.out)), indent=1))
