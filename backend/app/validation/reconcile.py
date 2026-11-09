"""Cross-verification: PDF ↔ PDF and PDF ↔ Excel reconciliation.

Takes the invoice records of two documents (e.g. a batch of invoice PDFs and
the accounts ledger in Excel), pairs them up and reports field-level
differences with a plain-language hint for common data-entry errors.

Matching order:
  1. exact normalised invoice number
  2. fuzzy invoice number (OCR slips such as O/0, I/1) - ratio >= 90
  3. same supplier + same total + same date (number missing on one side)
"""
from __future__ import annotations

from rapidfuzz import fuzz

from ..extraction.normalize import norm_invoice_number, norm_name

COMPARE_FIELDS = ["invoice_number", "invoice_date", "supplier_name", "customer_name", "subtotal", "tax", "total", "currency"]
AMOUNTS = {"subtotal", "tax", "total"}


_OCR_FOLD = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2", "G": "6"})


def ocr_fold(s: str) -> str:
    """Collapse characters OCR commonly confuses, for matching (never for display)."""
    return s.upper().translate(_OCR_FOLD)


def _digits(x: float) -> str:
    return f"{abs(x):.2f}".replace(".", "").lstrip("0")


def amount_hint(a: float, b: float) -> str | None:
    if a == 0 or b == 0:
        return None
    if sorted(_digits(a)) == sorted(_digits(b)) and _digits(a) != _digits(b):
        return "Same digits in a different order: likely a digit transposition."
    for factor in (10, 100, 1000):
        if abs(a * factor - b) < 0.011 or abs(b * factor - a) < 0.011:
            return f"Values differ by a factor of {factor}: likely a misplaced decimal point."
    if abs(a + b) < 0.011:
        return "Opposite signs: check debit/credit direction."
    if abs(a - b) < 1.0:
        return "Small difference: likely rounding."
    return None


def _equal(field: str, a, b, tol: float) -> bool:
    if field in AMOUNTS:
        return abs(float(a) - float(b)) <= tol
    if field == "invoice_number":
        return norm_invoice_number(a) == norm_invoice_number(b)
    if field in ("supplier_name", "customer_name"):
        na, nb = norm_name(a) or "", norm_name(b) or ""
        return na == nb or fuzz.token_sort_ratio(na, nb) >= 88
    return str(a).strip().upper() == str(b).strip().upper()


def compare_records(left: dict, right: dict, tol: float = 0.02) -> dict:
    diffs = []
    for f in COMPARE_FIELDS:
        a, b = left.get(f), right.get(f)
        if a is None and b is None:
            continue
        if a is None or b is None:
            diffs.append({"field": f, "left": a, "right": b, "status": "missing_left" if a is None else "missing_right"})
            continue
        if _equal(f, a, b, tol):
            diffs.append({"field": f, "left": a, "right": b, "status": "match"})
        else:
            d = {"field": f, "left": a, "right": b, "status": "mismatch"}
            if f in AMOUNTS:
                d["difference"] = round(float(b) - float(a), 2)
                d["hint"] = amount_hint(float(a), float(b))
            diffs.append(d)

    items = _compare_items(left.get("line_items") or [], right.get("line_items") or [], tol)
    mism = [d for d in diffs if d["status"] == "mismatch"] + [i for i in items if i["status"] != "match"]
    return {
        "left_id": left.get("id"),
        "right_id": right.get("id"),
        "status": "match" if not mism else "mismatch",
        "fields": diffs,
        "line_items": items,
        "mismatch_count": len(mism),
    }


def _compare_items(li: list[dict], ri: list[dict], tol: float) -> list[dict]:
    if not li or not ri:
        return []
    out, used = [], set()
    for a in li:
        best, best_s = None, 0
        for j, b in enumerate(ri):
            if j in used:
                continue
            s = fuzz.token_set_ratio((a.get("description") or "").lower(), (b.get("description") or "").lower())
            if s > best_s:
                best, best_s = j, s
        if best is None or best_s < 70:
            out.append({"description": a.get("description"), "status": "only_left", "left": a, "right": None})
            continue
        used.add(best)
        b = ri[best]
        bad = [k for k in ("quantity", "unit_price", "amount")
               if a.get(k) is not None and b.get(k) is not None and abs(float(a[k]) - float(b[k])) > tol]
        out.append({"description": a.get("description"), "status": "mismatch" if bad else "match",
                    "left": a, "right": b, "mismatched": bad})
    for j, b in enumerate(ri):
        if j not in used:
            out.append({"description": b.get("description"), "status": "only_right", "left": None, "right": b})
    return out


def merge_sheets(records: list[dict]) -> list[dict]:
    """One workbook often lists an invoice twice (ledger sheet + line-items sheet).
    Merge records with the same number from different sheets of the same document."""
    out: list[dict] = []
    index: dict[tuple, dict] = {}
    for r in records:
        num = norm_invoice_number(r.get("invoice_number"))
        key = (r.get("document_id"), num)
        if num and r.get("sheet_name") and key in index and index[key].get("sheet_name") != r.get("sheet_name"):
            base = index[key]
            for k, v in r.items():
                if base.get(k) in (None, [], "") and v not in (None, [], ""):
                    base[k] = v
            continue
        r = dict(r)
        out.append(r)
        if num:
            index.setdefault(key, r)
    return out


def reconcile(left: list[dict], right: list[dict], tol: float = 0.02) -> dict:
    left, right = merge_sheets(left), merge_sheets(right)
    pairs: list[tuple[dict, dict, str]] = []
    rl = list(range(len(right)))
    unmatched_left = []

    def take(j):
        rl.remove(j)
        return right[j]

    # pass 1: exact invoice number, for every record before any fuzzy matching, so
    # a near-duplicate can never take the partner of an exact match
    # When the same invoice arrived several times (re-sent, partially damaged copy),
    # compare the most complete copy; the others are reported as unmatched.
    def completeness(r: dict) -> int:
        return sum(r.get(f) is not None for f in COMPARE_FIELDS) + len(r.get("line_items") or [])

    used: set[int] = set()
    for j in list(rl):
        nb = norm_invoice_number(right[j].get("invoice_number"))
        cands = [i for i, a in enumerate(left) if i not in used and nb and norm_invoice_number(a.get("invoice_number")) == nb]
        if cands:
            best = max(cands, key=lambda i: completeness(left[i]))
            used.add(best)
            pairs.append((left[best], take(j), "invoice_number"))
    unmatched_left = [a for i, a in enumerate(left) if i not in used]

    # pass 2: invoice number with OCR slips (O/0, I/1, ...), or nearly equal and the
    # supplier or total agree too. Similar-looking numbers alone are not enough:
    # INV-1006 and INV-1065 are different invoices.
    rest = []
    for a in unmatched_left:
        na = norm_invoice_number(a.get("invoice_number"))
        hit = None
        if na:
            for j in rl:
                nb = norm_invoice_number(right[j].get("invoice_number")) or ""
                if ocr_fold(na) == ocr_fold(nb):
                    hit = j
                    break
            if hit is None:
                for j in rl:
                    b = right[j]
                    nb = norm_invoice_number(b.get("invoice_number")) or ""
                    same_total = a.get("total") is not None and b.get("total") is not None and abs(float(a["total"]) - float(b["total"])) <= tol
                    same_sup = (norm_name(a.get("supplier_name")) or "x") == (norm_name(b.get("supplier_name")) or "y")
                    if fuzz.ratio(na, nb) >= 90 and (same_total or same_sup):
                        hit = j
                        break
        if hit is not None:
            pairs.append((a, take(hit), "invoice_number_fuzzy"))
        else:
            rest.append(a)
    unmatched_left = rest

    # pass 3: supplier + total + date
    still_left = []
    for a in unmatched_left:
        hit = None
        for j in rl:
            b = right[j]
            if (a.get("total") is not None and b.get("total") is not None and abs(float(a["total"]) - float(b["total"])) <= tol
                    and a.get("invoice_date") == b.get("invoice_date")
                    and (norm_name(a.get("supplier_name")) or "") == (norm_name(b.get("supplier_name")) or "")):
                hit = j
                break
        if hit is not None:
            pairs.append((a, take(hit), "supplier_total_date"))
        else:
            still_left.append(a)

    results = []
    for a, b, how in pairs:
        r = compare_records(a, b, tol)
        r["matched_by"] = how
        r["invoice_number"] = a.get("invoice_number") or b.get("invoice_number")
        results.append(r)
    only_left = [{"id": a.get("id"), "invoice_number": a.get("invoice_number"), "total": a.get("total"), "supplier_name": a.get("supplier_name")} for a in still_left]
    only_right = [{"id": right[j].get("id"), "invoice_number": right[j].get("invoice_number"), "total": right[j].get("total"), "supplier_name": right[j].get("supplier_name")} for j in rl]

    sum_l = round(sum(float(x["total"]) for x in left if x.get("total") is not None), 2)
    sum_r = round(sum(float(x["total"]) for x in right if x.get("total") is not None), 2)
    summary = {
        "left_records": len(left),
        "right_records": len(right),
        "matched": len(results),
        "fully_consistent": sum(1 for r in results if r["status"] == "match"),
        "with_mismatches": sum(1 for r in results if r["status"] == "mismatch"),
        "only_in_left": len(only_left),
        "only_in_right": len(only_right),
        "left_total_sum": sum_l,
        "right_total_sum": sum_r,
        "total_sum_difference": round(sum_r - sum_l, 2),
    }
    return {"summary": summary, "pairs": results, "only_left": only_left, "only_right": only_right}
