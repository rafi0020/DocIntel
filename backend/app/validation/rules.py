"""Single-record validation rules.

Severity:
  error    the record is wrong or incomplete -> must be reviewed
  warning  the record may be wrong          -> must be reviewed
  info     context for the reviewer          -> does not block auto-approval
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from datetime import date, timedelta

from ..config import Settings, get_settings
from ..extraction.schema import ExtractedInvoice

LEDGER_REQUIRED = ["invoice_number", "total"]
DOC_REQUIRED = ["invoice_number", "invoice_date", "supplier_name", "total"]
DOC_EXPECTED = ["customer_name", "subtotal", "tax", "currency"]


@dataclass
class Issue:
    code: str
    severity: str
    message: str
    field: str | None = None
    details: dict = dc_field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def tolerance(amount: float, s: Settings) -> float:
    return max(s.amount_abs_tolerance, abs(amount) * s.amount_rel_tolerance)


def _label(name: str) -> str:
    return name.replace("_", " ")


def _fmt(x: float | None) -> str:
    return "—" if x is None else f"{x:,.2f}"


def validate_record(inv: ExtractedInvoice, s: Settings | None = None, today: date | None = None) -> list[Issue]:
    s = s or get_settings()
    today = today or date.today()
    issues: list[Issue] = []
    v = inv.value

    # 1. missing / unparseable / unverifiable fields
    required = LEDGER_REQUIRED if inv.record_kind == "ledger_row" else DOC_REQUIRED
    expected = [] if inv.record_kind == "ledger_row" else DOC_EXPECTED
    for name, fv in inv.fields.items():
        if fv.value is None and fv.candidate is not None:
            if fv.method is None and fv.source and "sheet" in fv.source:
                code = "invalid_date" if name == "invoice_date" else "invalid_number"
                issues.append(Issue(code, "error", fv.note or f"{_label(name)} is not valid", name, {"raw": fv.candidate}))
            else:
                issues.append(Issue("unverified_value", "warning",
                                    f"{name.replace('_', ' ').capitalize()}: extracted value '{fv.candidate}' was not found in the document, so it was left empty.",
                                    name, {"candidate": fv.candidate}))
        elif fv.value is None and name in required:
            issues.append(Issue("missing_field", "error", f"Required field missing: {_label(name)}.", name))
        elif fv.value is None and name in expected:
            issues.append(Issue("missing_field", "warning", f"Not found in the document: {_label(name)}.", name))

    subtotal, tax, total = v("subtotal"), v("tax"), v("total")

    # 2. numeric sanity
    if total is not None and total <= 0:
        issues.append(Issue("non_positive_total", "error" if total == 0 else "warning",
                            f"Total is {_fmt(total)} (zero or negative; credit note?).", "total"))
    for name, val in (("subtotal", subtotal), ("tax", tax)):
        if val is not None and val < 0:
            issues.append(Issue("negative_amount", "warning", f"{name} is negative ({_fmt(val)}).", name))
    if subtotal and tax is not None and subtotal > 0:
        if tax > subtotal:
            issues.append(Issue("tax_exceeds_subtotal", "error", f"Tax {_fmt(tax)} is larger than subtotal {_fmt(subtotal)}.", "tax"))
        elif tax / subtotal > s.max_tax_rate:
            issues.append(Issue("unusual_tax_rate", "warning", f"Tax rate {tax / subtotal:.0%} is unusually high.", "tax",
                                {"rate": round(tax / subtotal, 4)}))

    # 3. arithmetic consistency
    if subtotal is not None and tax is not None and total is not None:
        expected_total = subtotal + tax
        diff = round(total - expected_total, 2)
        if abs(diff) > tolerance(total, s):
            issues.append(Issue("total_mismatch", "error",
                                f"Subtotal {_fmt(subtotal)} + tax {_fmt(tax)} = {_fmt(expected_total)}, but total is {_fmt(total)} (difference {diff:+,.2f}).",
                                "total", {"expected": round(expected_total, 2), "actual": total, "difference": diff}))
    elif subtotal is not None and total is not None and tax is None and abs(total - subtotal) > tolerance(total, s):
        issues.append(Issue("total_mismatch", "warning",
                            f"Total {_fmt(total)} differs from subtotal {_fmt(subtotal)} and no tax amount was found.",
                            "total", {"expected": subtotal, "actual": total, "difference": round(total - subtotal, 2)}))

    items = inv.line_items
    amounts = [li.amount for li in items if li.amount is not None]
    if items and len(amounts) == len(items):
        items_sum = round(sum(amounts), 2)
        target_name, target = ("subtotal", subtotal) if subtotal is not None else (("total", total) if tax in (None, 0) else (None, None))
        if target is not None and abs(items_sum - target) > tolerance(target, s) + 0.01 * len(items):
            issues.append(Issue("line_items_mismatch", "error",
                                f"Line items add up to {_fmt(items_sum)}, but {target_name} is {_fmt(target)} (difference {target - items_sum:+,.2f}).",
                                target_name, {"items_sum": items_sum, target_name: target, "difference": round(target - items_sum, 2)}))
    elif items and amounts:
        issues.append(Issue("line_items_incomplete", "warning",
                            f"{len(items) - len(amounts)} of {len(items)} line items have no amount.", "line_items"))
    for i, li in enumerate(items):
        if li.quantity is not None and li.unit_price is not None and li.amount is not None:
            exp = round(li.quantity * li.unit_price, 2)
            if abs(exp - li.amount) > tolerance(li.amount, s):
                issues.append(Issue("line_item_arithmetic", "warning",
                                    f"Line {i + 1}: {li.quantity:g} × {_fmt(li.unit_price)} = {_fmt(exp)}, but amount is {_fmt(li.amount)}.",
                                    "line_items", {"index": i, "expected": exp, "actual": li.amount}))

    # 4. dates
    d = v("invoice_date")
    if d:
        dd = date.fromisoformat(d)
        if dd > today + timedelta(days=1):
            issues.append(Issue("future_date", "warning", f"Invoice date {d} is in the future.", "invoice_date"))
        elif dd.year < 2000:
            issues.append(Issue("implausible_date", "warning", f"Invoice date {d} looks implausible.", "invoice_date"))

    # 5. confidence / extractor signals
    for name, fv in inv.fields.items():
        if fv.value is None:
            continue
        if fv.note and fv.note.startswith("Extractors disagree"):
            issues.append(Issue("extractor_disagreement", "warning", f"{_label(name).capitalize()}: {fv.note}", name))
        elif fv.note and "ambiguous" in fv.note:
            issues.append(Issue("ambiguous_date", "warning", fv.note, name))
        elif fv.confidence < s.low_confidence_threshold:
            issues.append(Issue("low_confidence", "warning", f"Low confidence ({fv.confidence:.0%}) for {_label(name)}.", name,
                                {"confidence": fv.confidence}))
    for note in inv.notes:
        issues.append(Issue("llm_fallback", "info", note))
    return issues


def needs_review(issues: list[Issue] | list[dict]) -> bool:
    for i in issues:
        sev = i.severity if isinstance(i, Issue) else i["severity"]
        if sev in ("error", "warning"):
            return True
    return False
