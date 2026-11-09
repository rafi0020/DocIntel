"""Provenance: prove each extracted value exists in the document.

This is the "never invent values" guarantee. A value proposed by any extractor
(rules or LLM) is kept only if it can be located in the source text; the match
also yields the bounding box the UI highlights when a reviewer clicks a field.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from rapidfuzz import fuzz

from ..pipeline.doc_types import PageContent, Word
from .normalize import (
    amount_forms,
    find_amounts,
    find_dates,
    norm_invoice_number,
    parse_amount,
    parse_date,
)


@dataclass
class _Line:
    page: int
    text: str
    words: list[Word]
    offsets: list[tuple[int, int]]  # char span of each word in `text`


def build_lines(pages: list[PageContent]) -> list[_Line]:
    lines: list[_Line] = []
    for p in pages:
        if p.table is not None:
            continue
        by_line: dict[int, list[Word]] = {}
        for w in p.words:
            by_line.setdefault(w.line, []).append(w)
        if not by_line and p.text:
            for t in p.text.splitlines():
                lines.append(_Line(p.page_no, t, [], []))
            continue
        for _, ws in sorted(by_line.items()):
            ws = sorted(ws, key=lambda w: w.box[0])
            text, offs = "", []
            for w in ws:
                if text:
                    text += " "
                offs.append((len(text), len(text) + len(w.text)))
                text += w.text
            lines.append(_Line(p.page_no, text, ws, offs))
    return lines


def _box(line: _Line, start: int, end: int) -> dict:
    hit = [w for w, (s, e) in zip(line.words, line.offsets, strict=False) if s < end and e > start]
    if not hit:
        hit = line.words
    if not hit:
        return {"page": line.page}
    return {
        "page": line.page,
        "box": [
            round(min(w.box[0] for w in hit), 4),
            round(min(w.box[1] for w in hit), 4),
            round(max(w.box[2] for w in hit), 4),
            round(max(w.box[3] for w in hit), 4),
        ],
    }


def locate_amount(value, lines: list[_Line], prefer_last: bool = False) -> dict | None:
    target = parse_amount(value)
    if target is None:
        return None
    hits = []
    for ln in lines:
        for val, s, e in find_amounts(ln.text):
            if abs(abs(val) - abs(target)) < Decimal("0.005"):
                hits.append(_box(ln, s, e))
        if not hits:
            for form in amount_forms(target):
                idx = ln.text.find(form)
                if idx >= 0:
                    hits.append(_box(ln, idx, idx + len(form)))
                    break
    if not hits:
        return None
    return hits[-1] if prefer_last else hits[0]


def locate_date(value, lines: list[_Line], order: str) -> dict | None:
    target, _ = parse_date(value, order)
    if target is None:
        return None
    for ln in lines:
        for d, _, s, e in find_dates(ln.text, order):
            if d == target:
                return _box(ln, s, e)
        # Ambiguous day/month: accept the swapped reading too (flagged separately).
        for d, amb, s, e in find_dates(ln.text, "DMY" if order == "MDY" else "MDY"):
            if amb and d == target:
                return _box(ln, s, e)
    return None


def locate_code(value, lines: list[_Line]) -> dict | None:
    """Invoice numbers: compare alphanumerics only (OCR often inserts spaces)."""
    target = norm_invoice_number(value)
    if not target or len(target) < 2:
        return None
    for ln in lines:
        compact = re.sub(r"[^A-Za-z0-9]", "", ln.text).upper()
        if target in compact:
            # map back to a char span: find first word containing a chunk of the target
            for w, (s, e) in zip(ln.words, ln.offsets, strict=False):
                wn = norm_invoice_number(w.text) or ""
                if wn and (wn in target or target in wn):
                    return _box(ln, s, e)
            return _box(ln, 0, len(ln.text))
    return None


def locate_text(value, lines: list[_Line], threshold: int = 88) -> dict | None:
    if not value or len(str(value).strip()) < 2:
        return None
    target = str(value).strip().lower()
    best, best_score = None, 0
    for ln in lines:
        low = ln.text.lower()
        idx = low.find(target)
        if idx >= 0:
            return _box(ln, idx, idx + len(target))
        score = fuzz.partial_ratio(target, low)
        if score > best_score:
            best, best_score = ln, score
    if best is not None and best_score >= threshold:
        al = fuzz.partial_ratio_alignment(target, best.text.lower())
        return _box(best, al.dest_start, al.dest_end)
    return None


def locate_currency(value, lines: list[_Line]) -> dict | None:
    from .normalize import CURRENCY_SYMBOLS, CURRENCY_WORDS

    if not value:
        return None
    code = str(value).upper()
    needles = [code] + [s for s, c in CURRENCY_SYMBOLS.items() if c == code] + [w for w, c in CURRENCY_WORDS.items() if c == code]
    for ln in lines:
        for n in needles:
            m = re.search(rf"(?<![A-Za-z]){re.escape(n)}(?![A-Za-z])", ln.text, re.I if n.isalpha() else 0)
            if m:
                return _box(ln, m.start(), m.end())
    return None


def locate(field: str, value, lines: list[_Line], date_order: str = "MDY") -> dict | None:
    if value is None or value == "":
        return None
    if field in ("subtotal", "tax", "total"):
        return locate_amount(value, lines, prefer_last=True)
    if field == "invoice_date":
        return locate_date(value, lines, date_order)
    if field == "invoice_number":
        return locate_code(value, lines)
    if field == "currency":
        return locate_currency(value, lines)
    return locate_text(value, lines)
