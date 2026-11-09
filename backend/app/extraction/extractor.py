"""Combine rule-based and LLM candidates into one verified invoice record.

For each field:
  1. collect candidates (LLM, rules)
  2. keep only candidates that can be located in the document text (provenance)
  3. pick the best verified one and score confidence:
       LLM + rules agree ............ 0.95
       LLM only (verified) .......... 0.80
       extractors disagree .......... 0.60 (+ note, record goes to review)
       rules only ................... rule confidence (0.40-0.80)
     scaled by OCR quality on scanned pages
  4. nothing verified -> null, with the rejected candidate kept for the reviewer
"""
from __future__ import annotations

import logging
from decimal import Decimal

from rapidfuzz import fuzz

from ..pipeline.doc_types import PageContent
from ..runtime_settings import effective_settings
from .llm import LLMClient, LLMError
from .normalize import (
    CURRENCY_SYMBOLS,
    norm_invoice_number,
    norm_name,
    parse_amount,
    parse_date,
)
from .prompts import clip_text
from .provenance import build_lines, locate, locate_amount, locate_text
from .rules import extract_fields, extract_line_items
from .schema import AMOUNT_FIELDS, FIELDS, ExtractedInvoice, FieldValue, LineItem

log = logging.getLogger(__name__)


def _norm_value(field: str, v, order: str):
    """Bring a raw candidate to canonical form. Returns (value, ambiguous_date)."""
    if v is None or (isinstance(v, str) and v.strip().lower() in ("", "null", "none", "n/a")):
        return None, False
    if field in AMOUNT_FIELDS:
        a = parse_amount(v)
        return (float(a) if a is not None else None), False
    if field == "invoice_date":
        d, amb = parse_date(v, order)
        return (d.isoformat() if d else None), amb
    if field == "currency":
        s = str(v).strip()
        if s in CURRENCY_SYMBOLS:
            return CURRENCY_SYMBOLS[s], False
        s = s.upper()
        return (s if len(s) == 3 and s.isalpha() else None), False
    s = " ".join(str(v).split())
    return (s or None), False


def same_value(field: str, a, b) -> bool:
    if a is None or b is None:
        return False
    if field in AMOUNT_FIELDS:
        return abs(float(a) - float(b)) < 0.011
    if field == "invoice_number":
        return norm_invoice_number(a) == norm_invoice_number(b)
    if field in ("supplier_name", "customer_name"):
        na, nb = norm_name(a) or "", norm_name(b) or ""
        return na == nb or fuzz.token_sort_ratio(na, nb) >= 90 or (len(na) > 4 and (na in nb or nb in na))
    return str(a) == str(b)


def _ocr_factor(pages: list[PageContent], source: dict | None) -> float:
    if not source:
        return 1.0
    for p in pages:
        if p.page_no == source.get("page") and p.method == "ocr" and p.ocr_confidence is not None:
            return 0.6 + 0.4 * max(0.0, min(1.0, p.ocr_confidence))
    return 1.0


def _merge_field(field, llm_raw, rule, lines, pages, order) -> FieldValue:
    llm_val, llm_amb = _norm_value(field, llm_raw, order)
    rule_val, rule_amb = _norm_value(field, rule["value"], order) if rule else (None, False)
    llm_src = locate(field, llm_val, lines, order) if llm_val is not None else None
    rule_src = locate(field, rule_val, lines, order) if rule_val is not None else None

    fv = FieldValue()
    if llm_src and rule_src and same_value(field, llm_val, rule_val):
        fv = FieldValue(value=llm_val, confidence=0.95, source=llm_src, method="llm+rules")
    elif llm_src and rule_src:
        fv = FieldValue(
            value=llm_val, confidence=0.6, source=llm_src, method="llm",
            note=f"Extractors disagree: rule-based reading is '{rule_val}'.",
        )
    elif llm_src:
        fv = FieldValue(value=llm_val, confidence=0.8, source=llm_src, method="llm")
    elif rule_src:
        conf = float(rule.get("confidence", 0.5))
        if llm_raw is None and llm_val is None and rule.get("_llm_ran"):
            conf *= 0.9
        fv = FieldValue(value=rule_val, confidence=conf, source=rule_src, method="rules")
    else:
        rejected = llm_val if llm_val is not None else rule_val
        if rejected is not None:
            fv = FieldValue(value=None, confidence=0.0, candidate=rejected,
                            note="Proposed value could not be found in the document text, so it was not used.")
        return fv

    amb = (llm_amb if fv.method.startswith("llm") else rule_amb) if field == "invoice_date" else False
    if amb:
        fv.confidence *= 0.7
        fv.note = f"Day/month order is ambiguous; read as {order}."
    fv.confidence = round(fv.confidence * _ocr_factor(pages, fv.source), 3)
    return fv


def _verify_items(raw_items, lines) -> list[LineItem]:
    out: list[LineItem] = []
    for it in raw_items or []:
        if not isinstance(it, dict):
            continue
        desc = it.get("description")
        desc = " ".join(str(desc).split()) if desc else None
        amt = parse_amount(it.get("amount"))
        qty = parse_amount(it.get("quantity"))
        unit = parse_amount(it.get("unit_price"))
        amt_src = locate_amount(amt, lines) if amt is not None else None
        desc_src = locate_text(desc, lines, threshold=80) if desc else None
        if not amt_src and not desc_src:
            continue  # nothing about this row is on the page -> drop it
        q = float(qty) if qty is not None and locate_amount(qty, lines) else None
        u = float(unit) if unit is not None and locate_amount(unit, lines) else None
        a = float(amt) if amt_src else None
        conf = 0.9 if (amt_src and desc_src) else 0.6
        if q is not None and u is not None and a is not None and abs(q * u - a) > max(0.02, abs(a) * 0.01):
            conf = min(conf, 0.5)
        src = amt_src or desc_src
        if desc_src and amt_src and desc_src.get("page") == amt_src.get("page") and "box" in desc_src and "box" in amt_src:
            b1, b2 = desc_src["box"], amt_src["box"]
            src = {"page": desc_src["page"], "box": [min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3])]}
        out.append(LineItem(description=desc if desc_src else None, quantity=q, unit_price=u, amount=a,
                            confidence=conf, source=src))
    return out


def extract_from_pages(pages: list[PageContent], llm: LLMClient | None) -> ExtractedInvoice:
    s = effective_settings()
    order = s.ambiguous_date_order
    text = "\n\f\n".join(p.text for p in pages)  # \f marks page breaks for the table parser
    lines = build_lines(pages)

    rules = extract_fields(text, order)
    rule_items = extract_line_items(text)

    llm_data: dict = {}
    notes: list[str] = []
    extractor = "rules"
    if llm is not None:
        try:
            res = llm.extract(clip_text([(p.page_no, p.text) for p in pages], s.llm_max_chars))
            llm_data = res.data
            extractor = f"hybrid({llm.name})"
            for r in rules.values():
                r["_llm_ran"] = True
        except (LLMError, ValueError) as e:
            notes.append(f"LLM extraction failed, used rule-based extractor only: {e}")
            log.warning("LLM failed: %s", e)
        except Exception as e:  # noqa: BLE001 - never lose a document because the LLM broke
            notes.append(f"LLM extraction error, used rule-based extractor only: {type(e).__name__}: {e}")
            log.exception("LLM crashed")

    inv = ExtractedInvoice(raw_text=text, extractor=extractor, notes=notes)
    inv.page_start = pages[0].page_no if pages else None
    inv.page_end = pages[-1].page_no if pages else None
    for f in FIELDS:
        inv.fields[f] = _merge_field(f, llm_data.get(f), rules.get(f), lines, pages, order)

    items = _verify_items(llm_data.get("line_items"), lines) if llm_data else []
    if not items and rule_items:
        items = []
        for it in rule_items:
            src = locate_amount(it["amount"], lines) if it.get("amount") is not None else None
            ok = it.get("quantity") is not None and it.get("unit_price") is not None
            items.append(LineItem(**it, confidence=0.7 if ok else 0.5, source=src))
    inv.line_items = items
    return inv


def decimal_or_none(v) -> Decimal | None:
    return parse_amount(v)
