"""Deterministic, label-driven invoice extractor.

Works with no LLM at all, and runs alongside the LLM as a cross-check: when
both agree on a value, confidence goes up; when they disagree the record is
flagged. Every pattern looks for a printed label ("Invoice No", "Total Due"...)
and reads the value next to it, so it only ever returns text that is on the page.
"""
from __future__ import annotations

import re
from decimal import Decimal

from .normalize import detect_currency, find_amounts, find_dates

_INV_LABEL = re.compile(
    r"\b(?:invoice|inv|bill|tax\s+invoice)\s*(?:no\.?|number|num|#|id|ref(?:erence)?)\s*[:#.\-]?\s*"
    r"(?P<val>[A-Za-z0-9][A-Za-z0-9\-/_.]*\d[A-Za-z0-9\-/_]*)",
    re.I,
)
_INV_LABEL_LOOSE = re.compile(r"\b(?:invoice|inv)\s*[:#]\s*(?P<val>[A-Za-z0-9][A-Za-z0-9\-/_.]*\d[A-Za-z0-9\-/_]*)", re.I)
_DATE_LABEL = re.compile(r"\b(?:invoice\s+date|date\s+of\s+issue|issue\s+date|issued(?:\s+on)?|bill\s+date|date)\b\s*[:.]?", re.I)
_DUE = re.compile(r"\b(?:due|payment|period|service|delivery|from|to)\b", re.I)

# label followed by ":" / "-" or, when OCR dropped the colon, by a wide column gap
_SUPPLIER_LABEL = re.compile(r"^\s*(?:from|supplier|vendor|seller|billed\s+by|issued\s+by|provider)\s*(?:[:;\-]|\s{3,})\s*(?P<val>.*)$", re.I)
_CUSTOMER_LABEL = re.compile(r"^\s*(?:bill(?:ed)?\s+to|customer|client|sold\s+to|invoice\s+to|buyer)\s*[:\-]?\s*(?P<val>.*)$", re.I)

_SUBTOTAL = re.compile(r"\b(?:sub[\s\-]?total|net\s+amount|total\s+net(?:\s+worth)?|net\s+worth|amount\s+before\s+tax|taxable\s+amount)\b", re.I)
_TAX = re.compile(r"\b(?:tax|vat|gst|hst|sales\s+tax)\b(?!\s*(?:i\.?d|ld|no|number|reg|#|\[?%))", re.I)
_TOTAL = re.compile(
    r"\b(?:grand\s+total|total\s+due|amount\s+due|total\s+amount(?:\s+due)?|balance\s+due|total\s+payable|"
    r"amount\s+payable|invoice\s+total|total\s+gross(?:\s+worth)?|total)\b",
    re.I,
)
_TOTAL_EXCLUDE = re.compile(r"\b(?:sub[\s\-]?total|total\s+tax|total\s+vat|total\s+net|total\s+hours|total\s+qty|total\s+quantity|items?)\b", re.I)

_ITEM_HEADER_DESC = re.compile(r"\b(?:description|item|service|particulars|details|product)\b", re.I)
_ITEM_HEADER_AMT = re.compile(r"\b(?:amount|total|line\s+total|price|rate|worth)\b", re.I)
_COL_WORDS = re.compile(r"\b(?:qty|quantity|hours|units|rate|price|amount|total|description|item|service|particulars|worth)\b", re.I)
_STOP = re.compile(r"\b(?:sub[\s\-]?total|total|tax|vat|summary|amount\s+due|balance)\b", re.I)
_ORG = re.compile(r"\b(?:inc|llc|ltd|limited|co|corp|company|plc|gmbh|group|agency|services|solutions|partners|supplies)\b\.?", re.I)
_NOISE_FIRST = re.compile(r"^(?:tax\s+)?invoice\b|^page\s+\d|^\W*$", re.I)


def _amount_on_line(line: str) -> Decimal | None:
    amts = [a for a in find_amounts(line) if not _is_percent(line, a[2])]
    return amts[-1][0] if amts else None


def _is_percent(line: str, end: int) -> bool:
    return line[end : end + 2].strip().startswith("%")


def _value_after_label(lines: list[str], i: int, m: re.Match) -> str | None:
    val = (m.group("val") or "").strip(" :-\t")
    if val:
        return re.split(r"\s{3,}", val)[0].strip() or None
    # Value on the next non-empty line
    for j in range(i + 1, min(i + 3, len(lines))):
        nxt = lines[j].strip()
        if nxt:
            return re.split(r"\s{3,}", nxt)[0].strip()
    return None


def extract_fields(text: str, date_order: str = "MDY") -> dict[str, dict]:
    """Return {field: {"value": ..., "confidence": float}} for labels found in text."""
    lines = text.splitlines()
    out: dict[str, dict] = {}

    # invoice number
    for pat, conf in ((_INV_LABEL, 0.8), (_INV_LABEL_LOOSE, 0.6)):
        for ln in lines:
            m = pat.search(ln)
            if m and not re.match(r"(?i)date", m.group("val")):
                out["invoice_number"] = {"value": m.group("val").rstrip(".,"), "confidence": conf}
                break
        if "invoice_number" in out:
            break

    # invoice date: prefer labelled, non-due date; else first date in document
    best = None
    for ln in lines:
        m = _DATE_LABEL.search(ln)
        if not m:
            continue
        label = m.group(0)
        if _DUE.search(ln[: m.start()] + label):
            continue
        ds = find_dates(ln[m.end() :], date_order)
        if ds:
            best = (ds[0], 0.8)
            break
    if best is None:
        all_d = find_dates(text, date_order)
        if all_d:
            best = (all_d[0], 0.45)
    if best:
        (d, amb, _, _), conf = best
        out["invoice_date"] = {"value": d.isoformat(), "confidence": conf * (0.7 if amb else 1.0), "ambiguous": amb}

    # supplier / customer: two-column blocks ("Seller:      Client:") first
    for i, ln in enumerate(lines):
        cols = [c.strip() for c in re.split(r"\s{3,}", ln.strip()) if c.strip()]
        if len(cols) == 2 and _SUPPLIER_LABEL.match(cols[0]) and _CUSTOMER_LABEL.match(cols[1]):
            for j in range(i + 1, min(i + 4, len(lines))):
                nxt = [c.strip() for c in re.split(r"\s{3,}", lines[j].strip()) if c.strip()]
                if len(nxt) >= 2:
                    out["supplier_name"] = {"value": nxt[0], "confidence": 0.75}
                    out["customer_name"] = {"value": nxt[1], "confidence": 0.75}
                    break
            break
    for i, ln in enumerate(lines):
        if "supplier_name" not in out:
            m = _SUPPLIER_LABEL.match(ln)
            if m:
                v = _value_after_label(lines, i, m)
                if v:
                    out["supplier_name"] = {"value": v, "confidence": 0.75}
        if "customer_name" not in out:
            m = _CUSTOMER_LABEL.match(ln)
            if m:
                v = _value_after_label(lines, i, m)
                if v:
                    out["customer_name"] = {"value": v, "confidence": 0.75}
    if "supplier_name" not in out:
        # Letterhead heuristic: first meaningful line at the top of the page.
        for ln in lines[:6]:
            s = re.split(r"\s{3,}", ln.strip())[0]
            if s and not _NOISE_FIRST.search(s) and sum(c.isalpha() for c in s) >= 4 and not find_dates(s):
                if not _INV_LABEL.search(s):
                    # Letterhead guess. Confidence calibrated on the dev split: a first line
                    # that looks like an organisation name was right in ~95% of cases.
                    org_like = bool(_ORG.search(s)) or sum(w[:1].isupper() for w in s.split()) >= 2
                    out["supplier_name"] = {"value": s, "confidence": 0.6 if org_like else 0.4}
                    break

    # amounts in a summary table with a header row ("Net worth   VAT   Gross worth")
    _summary_table(lines, out)

    # amounts: search bottom-up, totals live at the end
    for ln in reversed(lines):
        if "total" not in out and _TOTAL.search(ln) and not _TOTAL_EXCLUDE.search(ln):
            a = _amount_on_line(ln)
            if a is not None:
                out["total"] = {"value": str(a), "confidence": 0.8}
                continue
        if "subtotal" not in out and _SUBTOTAL.search(ln):
            a = _amount_on_line(ln)
            if a is not None:
                out["subtotal"] = {"value": str(a), "confidence": 0.8}
                continue
        if "tax" not in out and _TAX.search(ln) and not _SUBTOTAL.search(ln):
            a = _amount_on_line(ln)
            if a is not None:
                out["tax"] = {"value": str(a), "confidence": 0.7}

    cur, _ = detect_currency(text)
    if cur:
        out["currency"] = {"value": cur, "confidence": 0.7}
    return out


_COL_LABELS = [
    ("subtotal", _SUBTOTAL),
    ("tax", re.compile(r"^(?:tax|vat|gst|sales\s+tax|tax\s+amount|vat\s+amount)$", re.I)),
    ("total", re.compile(r"^(?:total|gross(?:\s+worth)?|grand\s+total|amount\s+due|total\s+due|gross\s+amount)$", re.I)),
]


def _summary_table(lines: list[str], out: dict) -> None:
    """Header row of labels followed by a row of values, aligned from the right."""
    for i in range(len(lines) - 1, -1, -1):
        cols = [c.strip() for c in re.split(r"\s{2,}", lines[i].strip()) if c.strip()]
        if len(cols) < 2 or find_amounts(lines[i]):
            continue
        roles = []
        for c in cols:
            role = None
            for name, pat in _COL_LABELS:
                if pat.search(c) if name == "subtotal" else pat.match(c):
                    role = name
                    break
            roles.append(role)
        if sum(r is not None for r in roles) < 2:
            continue
        for j in range(i + 1, min(i + 4, len(lines))):
            vals = [a for a in find_amounts(lines[j]) if not _is_percent(lines[j], a[2])]
            if len(vals) >= sum(r is not None for r in roles):
                # align from the right: last label <-> last value
                for role, (val, _, _) in zip(reversed(roles), reversed(vals), strict=False):
                    if role and role not in out:
                        out[role] = {"value": str(val), "confidence": 0.75}
                return
        return


def _best_triple(vals: list[float]) -> tuple[int, int, int] | None:
    """Indices (q, u, a) with q * u == a, scanning left to right."""
    n = len(vals)
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                q, u, a = vals[i], vals[j], vals[k]
                if a and abs(q * u - a) <= max(0.02, abs(a) * 0.005):
                    return i, j, k
    return None


def extract_line_items(text: str) -> list[dict]:
    """Parse the item table page by page (each page repeats its own table header)."""
    items: list[dict] = []
    for page_text in text.split("\f"):
        items.extend(_items_on_page(page_text))
    return items


def _items_on_page(text: str) -> list[dict]:
    """Parse one page's item table: rows ending in (qty, unit price, amount) or (amount)."""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if len(find_amounts(ln)) or _SUBTOTAL.search(ln):
            continue
        hits = len(_COL_WORDS.findall(ln))
        if (_ITEM_HEADER_DESC.search(ln) and _ITEM_HEADER_AMT.search(ln)) or hits >= 3:
            start = i + 1
            break
    if start is None:
        # OCR may have destroyed the header row: start at the first row whose numbers
        # are internally consistent (qty x price = amount)
        for i, ln in enumerate(lines):
            if _best_triple([float(a[0]) for a in find_amounts(ln) if not _is_percent(ln, a[2])]):
                start = i
                break
    if start is None:
        return []
    items: list[dict] = []
    for ln in lines[start:]:
        s = ln.strip()
        if not s:
            continue
        if (_STOP.search(s) or _SUBTOTAL.search(s)) and len(find_amounts(s)) <= 2 and not items_have_desc_only(s):
            break
        nums = [a for a in find_amounts(s) if not _is_percent(s, a[2])]
        if not nums:
            if items and len(s) < 120:
                items[-1]["description"] = ((items[-1]["description"] or "") + " " + s).strip()
            continue
        # leading row numbers like "1." are not values
        if nums and nums[0][1] <= 3 and re.match(r"^\s*\d{1,3}[.)]?\s", s):
            nums = nums[1:]
        vals = [float(n[0]) for n in nums]
        triple = _best_triple(vals)
        has_money = any(re.search(r"\d[.,]\d{2}\b", s[a:b]) for _, a, b in nums)
        if triple is None and not (has_money and len(vals) >= 1):
            # continuation of a wrapped description (e.g. sizes like 15")
            if items and len(s) < 120:
                items[-1]["description"] = (items[-1]["description"] or "") + " " + s
            continue
        if triple:
            qi, ui, ai = triple
            desc = s[: nums[qi][1]].strip(" -:\t|")
            item = {"description": None, "quantity": vals[qi], "unit_price": vals[ui], "amount": vals[ai]}
        elif len(vals) >= 3:
            # no consistent triple: read the last three columns as qty / price / amount so
            # the validator can flag the arithmetic error instead of hiding it
            desc = s[: nums[-3][1]].strip(" -:\t|")
            item = {"description": None, "quantity": vals[-3], "unit_price": vals[-2], "amount": vals[-1]}
        else:
            desc = s[: nums[0][1]].strip(" -:\t|")
            item = {"description": None, "quantity": None, "unit_price": None, "amount": vals[-1]}
            if len(vals) == 2 and vals[0] == int(vals[0]) and vals[0] < 1000:
                item["quantity"] = vals[0]
        desc = re.sub(r"^\d{1,3}[.)]?\s+", "", desc).strip()
        item["description"] = desc or None
        items.append(item)
    for it in items:
        if it["description"]:
            it["description"] = " ".join(it["description"].split())
    return items


def items_have_desc_only(s: str) -> bool:
    # "Total hours of care" style descriptions must not stop the table
    return bool(re.match(r"(?i)^(?:\d+\.?\s+)?[a-z].*(?:visit|care|hours|service|nursing)", s)) and not re.search(
        r"(?i)\b(?:sub[\s-]?total|grand total|total due|amount due)\b", s
    )
