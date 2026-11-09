"""Evaluate the pipeline against a labelled dataset and write a report.

Runs the exact code path the background worker runs (`process_document`) on
every file of a manifest and scores:

  * field accuracy           per field and overall (null-vs-null counts as correct;
                             a value where the truth is null counts as a hallucination)
  * line items               precision / recall / F1 (match = similar description AND
                             equal amount)
  * validation               recall on planted errors, false-alarm rate on clean docs
  * splitting                invoices found vs. expected in multi-invoice PDFs
  * cross-verification       detection of deliberately altered ledger rows
  * robustness               success rate, graceful-failure rate, crash rate
  * speed                    per-file and per-page latency (p50 / p95), throughput

Usage:
  python -m eval.run_eval --manifest ../dataset/synthetic_test/manifest.json --out ../eval_results/synthetic_test
  LLM_PROVIDER=rules python -m eval.run_eval ...   # rules-only baseline
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path

from rapidfuzz import fuzz

from app.config import get_settings
from app.extraction.normalize import norm_invoice_number, norm_name
from app.extraction.schema import FIELDS
from app.pipeline.doc_types import IngestError
from app.pipeline.process import process_document
from app.validation.reconcile import reconcile

AMOUNT = {"subtotal", "tax", "total"}


def name_match(pred: str, gt: str, gt_has_address: bool) -> bool:
    p, g = norm_name(pred) or "", norm_name(gt) or ""
    if not p or not g:
        return False
    if p == g or fuzz.token_sort_ratio(p, g) >= 90:
        return True
    if gt_has_address:
        # label = "Name Street City..." -> the prediction must be the leading name part
        return g.startswith(p) and len(p) >= 3
    return False


def field_correct(f: str, pred, gt, gt_has_address=False) -> bool:
    if gt is None:
        return pred is None
    if pred is None:
        return False
    if f in AMOUNT:
        return abs(float(pred) - float(gt)) <= 0.011
    if f == "invoice_number":
        return norm_invoice_number(pred) == norm_invoice_number(gt)
    if f in ("supplier_name", "customer_name"):
        return name_match(pred, gt, gt_has_address)
    return str(pred).upper() == str(gt).upper()


def score_items(pred: list[dict], gt: list[dict]) -> tuple[int, int, int]:
    used, tp = set(), 0
    for g in gt:
        for j, p in enumerate(pred):
            if j in used or p.get("amount") is None or g.get("amount") is None:
                continue
            if abs(float(p["amount"]) - float(g["amount"])) <= 0.011 and fuzz.token_set_ratio(
                (p.get("description") or "").lower(), (g.get("description") or "").lower()
            ) >= 70:
                used.add(j)
                tp += 1
                break
    return tp, len(pred), len(gt)


def pair_records(pred: list[dict], gt: list[dict]) -> list[tuple[dict | None, dict | None]]:
    if len(pred) == 1 and len(gt) == 1:
        return [(pred[0], gt[0])]
    pairs, used = [], set()
    for g in gt:
        hit = None
        gn = norm_invoice_number(g.get("invoice_number"))
        for j, p in enumerate(pred):
            if j not in used and gn and norm_invoice_number(p.get("invoice_number")) == gn:
                hit = j
                break
        if hit is None:  # fall back to position
            cand = [j for j in range(len(pred)) if j not in used]
            hit = cand[0] if cand else None
        if hit is not None:
            used.add(hit)
        pairs.append((pred[hit] if hit is not None else None, g))
    for j, p in enumerate(pred):
        if j not in used:
            pairs.append((p, None))
    return pairs


def pct(x, n):
    return round(100.0 * x / n, 1) if n else None


def percentile(vals, q):
    if not vals:
        return None
    v = sorted(vals)
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 1)


def run(manifest_path: Path, out_dir: Path, limit: int | None = None) -> dict:
    s = get_settings()
    manifest = json.loads(manifest_path.read_text())
    root = manifest_path.parent / "files"
    files = manifest["files"][:limit] if limit else manifest["files"]
    out_dir.mkdir(parents=True, exist_ok=True)

    per_file = []
    field_hits = Counter()
    field_total = Counter()
    halluc = Counter()
    misses = Counter()
    item_tp = item_pred = item_gt = 0
    planted_total = planted_found = 0
    clean_docs = clean_flagged = 0
    issue_recall = defaultdict(lambda: [0, 0])
    lat_by_cat = defaultdict(list)
    per_page = defaultdict(list)
    outcomes = Counter()
    provenance_rejections = provenance_fields = 0
    by_quality = defaultdict(lambda: [0, 0])
    records_by_file: dict[str, list[dict]] = {}

    for i, entry in enumerate(files):
        data = (root / entry["file"]).read_bytes()
        t0 = time.perf_counter()
        rec = {"file": entry["file"], "kind": entry["kind"], "format": entry.get("format"), "quality": entry.get("quality")}
        try:
            out = process_document(data, entry["file"])
            ms = (time.perf_counter() - t0) * 1000
            rec.update(status="ok", ms=round(ms, 1), pages=len(out.ingest.pages), source_kind=out.ingest.source_kind,
                       extractor=out.extractor, records=len(out.records))
            preds = []
            for r in out.records:
                j = r.invoice.to_output_json()
                j["_issues"] = [x.code for x in r.issues if x.severity in ("error", "warning")]
                j["_rejected"] = sum(1 for f in r.invoice.fields.values() if f.candidate is not None and f.value is None)
                preds.append(j)
                provenance_rejections += j["_rejected"]
                provenance_fields += len(FIELDS)
            records_by_file[entry["file"]] = preds
        except IngestError as e:
            ms = (time.perf_counter() - t0) * 1000
            rec.update(status="failed", ms=round(ms, 1), error_code=e.code, error=e.message)
            preds = None
        except Exception as e:  # noqa: BLE001 - a crash is a finding, not a reason to stop
            ms = (time.perf_counter() - t0) * 1000
            rec.update(status="crashed", ms=round(ms, 1), error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-800:])
            preds = None

        expected = entry.get("expected", "ok")
        if expected == "ok":
            outcomes["ok_expected_ok" if rec["status"] == "ok" else f"{rec['status']}_expected_ok"] += 1
        elif expected == "fail":
            if rec["status"] == "failed":
                outcomes["graceful_failure"] += 1
                rec["error_code_correct"] = rec.get("error_code") == entry.get("expected_error")
            elif rec["status"] == "ok":
                outcomes["accepted_bad_file"] += 1
            else:
                outcomes["crashed_on_bad_file"] += 1
        else:
            outcomes[f"{rec['status']}_on_damaged_file"] += 1

        if rec["status"] == "ok":
            cat = rec["source_kind"] if entry["kind"] != "batch" else "batch_pdf"
            lat_by_cat[cat].append(rec["ms"])
            per_page[cat].append(rec["ms"] / max(1, rec["pages"]))

        # ---- accuracy (invoice documents only; ledgers/batches scored separately)
        if preds is not None and entry["kind"] in ("invoice", "batch") and expected == "ok":
            has_addr = entry.get("name_fields_include_address", False)
            ok_fields = n_fields = 0
            for p, g in pair_records(preds, entry["invoices"]):
                if g is None:
                    continue
                for f in FIELDS:
                    pv = p.get(f) if p else None
                    gv = g.get(f)
                    c = field_correct(f, pv, gv, has_addr)
                    field_total[f] += 1
                    field_hits[f] += c
                    n_fields += 1
                    ok_fields += c
                    if not c and gv is None and pv is not None:
                        halluc[f] += 1
                    if not c and gv is not None and pv is None:
                        misses[f] += 1
                if g.get("line_items") is not None:
                    tp, np_, ng = score_items(p.get("line_items", []) if p else [], g["line_items"])
                    item_tp, item_pred, item_gt = item_tp + tp, item_pred + np_, item_gt + ng
            rec["field_accuracy"] = pct(ok_fields, n_fields)
            q = entry.get("quality", "batch")
            by_quality[q][0] += ok_fields
            by_quality[q][1] += n_fields
            if entry["kind"] == "batch":
                rec["invoices_expected"] = len(entry["invoices"])
                rec["invoices_found"] = len(preds)

            # ---- validation (single-record issues)
            planted = [c for c in entry.get("planted_issues", []) if c != "duplicate_invoice"]
            found_codes = set(preds[0]["_issues"]) if preds and entry["kind"] == "invoice" else set()
            if entry["kind"] == "invoice":
                if planted:
                    for c in planted:
                        planted_total += 1
                        hit = c in found_codes
                        planted_found += hit
                        issue_recall[c][0] += hit
                        issue_recall[c][1] += 1
                elif "duplicate_invoice" not in entry.get("planted_issues", []):
                    clean_docs += 1
                    if found_codes:
                        clean_flagged += 1
                        rec["false_alarm_codes"] = sorted(found_codes)
        per_file.append(rec)
        print(f"[{i + 1}/{len(files)}] {entry['file']:<32} {rec['status']:<8} {rec['ms']:>9.0f} ms  acc={rec.get('field_accuracy')}", flush=True)

    # ---- cross-verification: invoice docs vs the ledger
    recon = None
    ledgers = [e for e in files if e["kind"] == "ledger" and e["format"] == "xlsx" and e["file"] in records_by_file]
    if ledgers:
        led = ledgers[0]
        right = [{**r, "id": f"L{k}"} for k, r in enumerate(records_by_file[led["file"]])]
        left = []
        for e in files:
            if e["kind"] == "invoice" and not e["file"].startswith("dup_") and e["file"] in records_by_file:
                for r in records_by_file[e["file"]]:
                    left.append({**r, "id": e["file"]})
        res = reconcile(left, right)
        altered = {(norm_invoice_number(a["invoice_number"]), a["field"]) for a in led.get("altered_rows", [])}
        flagged = set()
        for pr in res["pairs"]:
            for d in pr["fields"]:
                if d["status"] == "mismatch":
                    flagged.add((norm_invoice_number(pr["invoice_number"]), d["field"]))
        tp = len(altered & flagged)
        recon = {
            "summary": res["summary"],
            "altered_rows": len(altered),
            "altered_detected": tp,
            "detection_recall": pct(tp, len(altered)),
            "flagged_field_mismatches": len(flagged),
            "false_flags": len(flagged - altered),
            "false_flag_examples": sorted(flagged - altered)[:10],
        }

    ok_lat = [r["ms"] for r in per_file if r["status"] == "ok"]
    expected_ok = sum(1 for e in files if e.get("expected", "ok") == "ok")
    expected_fail = sum(1 for e in files if e.get("expected") == "fail")
    item_p = item_tp / item_pred if item_pred else 0
    item_r = item_tp / item_gt if item_gt else 0
    summary = {
        "dataset": str(manifest_path.parent.name),
        "extractor": next((r["extractor"] for r in per_file if r.get("extractor")), None),
        "llm_provider": s.llm_provider,
        "ocr_engine": s.ocr_engine,
        "files": len(files),
        "robustness": {
            "expected_ok": expected_ok,
            "processed_ok": outcomes["ok_expected_ok"],
            "document_success_rate_pct": pct(outcomes["ok_expected_ok"], expected_ok),
            "failure_rate_pct": pct(expected_ok - outcomes["ok_expected_ok"], expected_ok),
            "bad_files": expected_fail,
            "bad_files_rejected_gracefully": outcomes["graceful_failure"],
            "bad_files_with_correct_error_code": sum(1 for r in per_file if r.get("error_code_correct")),
            "crashes": sum(1 for r in per_file if r["status"] == "crashed"),
            "outcomes": dict(outcomes),
        },
        "accuracy": {
            "overall_field_accuracy_pct": pct(sum(field_hits.values()), sum(field_total.values())),
            "per_field_pct": {f: pct(field_hits[f], field_total[f]) for f in FIELDS},
            "hallucinated_values": dict(halluc),
            "missed_values": dict(misses),
            "line_items": {"precision_pct": pct(item_tp, item_pred), "recall_pct": pct(item_tp, item_gt),
                           "f1_pct": round(200 * item_p * item_r / (item_p + item_r), 1) if item_p + item_r else None,
                           "matched": item_tp, "predicted": item_pred, "expected": item_gt},
            "by_scan_quality_pct": {q: pct(a, b) for q, (a, b) in by_quality.items()},
            "provenance_rejections": provenance_rejections,
            "provenance_rejection_rate_pct": pct(provenance_rejections, provenance_fields),
        },
        "validation": {
            "planted_issues": planted_total,
            "detected": planted_found,
            "recall_pct": pct(planted_found, planted_total),
            "recall_by_code": {k: f"{a}/{b}" for k, (a, b) in issue_recall.items()},
            "clean_documents": clean_docs,
            "clean_documents_flagged_for_review": clean_flagged,
            "false_alarm_rate_pct": pct(clean_flagged, clean_docs),
        },
        "splitting": [
            {"file": r["file"], "expected": r.get("invoices_expected"), "found": r.get("invoices_found"), "pages": r.get("pages")}
            for r in per_file if r["kind"] == "batch"
        ],
        "cross_verification": recon,
        "speed": {
            "total_wall_s": round(sum(ok_lat) / 1000, 1),
            "per_file_ms": {"p50": percentile(ok_lat, 0.5), "p95": percentile(ok_lat, 0.95), "max": max(ok_lat) if ok_lat else None},
            "by_type_ms": {k: {"n": len(v), "p50": percentile(v, 0.5), "p95": percentile(v, 0.95)} for k, v in lat_by_cat.items()},
            "per_page_ms": {k: {"p50": percentile(v, 0.5), "p95": percentile(v, 0.95)} for k, v in per_page.items()},
            "throughput_docs_per_min": round(60000 * len(ok_lat) / sum(ok_lat), 1) if ok_lat else None,
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    (out_dir / "per_file.json").write_text(json.dumps(per_file, indent=1, default=str))
    (out_dir / "predictions.json").write_text(json.dumps(records_by_file, indent=1, default=str))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    summ = run(Path(a.manifest), Path(a.out), a.limit)
    print(json.dumps({k: summ[k] for k in ("robustness", "accuracy", "validation", "cross_verification", "speed")}, indent=1, default=str))
