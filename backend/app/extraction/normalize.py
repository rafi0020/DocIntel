"""Parsing/normalisation helpers shared by extraction, provenance and validation."""
from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CURRENCY_CODES = {
    "USD", "EUR", "GBP", "BDT", "INR", "CAD", "AUD", "JPY", "CNY", "SGD", "AED", "SAR", "CHF",
    "PKR", "NZD", "MYR", "THB", "HKD", "SEK", "NOK", "DKK", "PLN", "ZAR",
}
# Symbols map to a currency only where the symbol is unambiguous in practice.
CURRENCY_SYMBOLS = {"€": "EUR", "£": "GBP", "৳": "BDT", "₹": "INR", "¥": "JPY", "$": "USD"}
CURRENCY_WORDS = {"tk": "BDT", "taka": "BDT", "rs": "INR", "us$": "USD", "dollars": "USD", "euro": "EUR", "euros": "EUR"}

MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
            ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
            ("oct", "october"), ("nov", "november"), ("dec", "december"),
        ]
    )
    for m in names
}

AMOUNT_RE = re.compile(
    r"(?<![\w.,])[-(]?\s*(?:[$€£৳₹¥]|[A-Z]{3}\s?)?\s*-?\d{1,3}(?:[ ,. ']\d{3})*(?:[.,]\d{1,2})?\)?(?![\w])"
    r"|(?<![\w.,])[-(]?\s*(?:[$€£৳₹¥]|[A-Z]{3}\s?)?\s*-?\d+(?:[.,]\d{1,2})?\)?(?![\w])"
)

_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_PATTERNS = [
    re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b"),  # ISO
    re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b"),  # 03/04/2026
    re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s\-.]+({_MONTH_ALT})\.?[\s\-.,]+(\d{{4}})\b", re.I),  # 4 Mar 2026
    re.compile(rf"\b({_MONTH_ALT})\.?[\s\-]+(\d{{1,2}})(?:st|nd|rd|th)?,?[\s\-]+(\d{{4}})\b", re.I),  # Mar 4, 2026
]


def parse_amount(raw) -> Decimal | None:
    """Parse '1,234.56', '1.234,56', '$ 1 234', '(45.00)' etc. Returns None if not a number."""
    if raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)):
        try:
            return Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            return None
    s = str(raw).strip()
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")") or s.startswith("-") or s.endswith("-")
    s = re.sub(r"[^\d.,]", "", s.replace(" ", " ").replace("'", ""))
    if not s or not any(ch.isdigit() for ch in s):
        return None
    if "," in s and "." in s:
        # whichever separator appears last is the decimal separator
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        # "1,234" (thousands) vs "12,50" (decimal comma)
        s = s.replace(",", "") if len(tail) == 3 and head else head.replace(",", "") + "." + tail
    elif s.count(".") > 1:
        head, _, tail = s.rpartition(".")
        s = head.replace(".", "") + ("." + tail if len(tail) <= 2 else tail)
    elif "." in s:
        head, _, tail = s.rpartition(".")
        if len(tail) == 3 and len(head) <= 3 and head:
            # "1.234" is ambiguous; in invoices with 2-decimal money it's almost always thousands
            s = head + tail
    try:
        val = Decimal(s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
    return -val if neg else val


def amount_forms(value: Decimal) -> list[str]:
    """Textual forms an amount may take on a page (used for provenance lookup)."""
    v = abs(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    whole, frac = f"{v:.2f}".split(".")
    with_commas = f"{int(whole):,}"
    forms = {
        f"{whole}.{frac}", f"{with_commas}.{frac}",
        f"{with_commas.replace(',', '.')},{frac}", f"{with_commas.replace(',', ' ')},{frac}",
        f"{whole},{frac}",
    }
    if frac == "00":
        forms |= {whole, with_commas}
    return sorted(forms, key=len, reverse=True)


# OCR often turns the decimal separator into a space: "255.499 60", "Tk 367.571 62".
# Only repaired when the number already has a thousands group, so a quantity next
# to a price ("12 45.00") is never glued together.
SPLIT_DECIMAL_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})+) (\d{2})(?![\d.,])")


def find_amounts(text: str) -> list[tuple[Decimal, int, int]]:
    out = []
    for m in SPLIT_DECIMAL_RE.finditer(text):
        val = parse_amount(f"{m.group(1)}.{m.group(2)}")
        if val is not None:
            out.append((val, m.start(), m.end()))
    if out:  # mask repaired spans so the generic pattern doesn't re-read their halves
        masked = list(text)
        for _, a, b in out:
            masked[a:b] = " " * (b - a)
        text = "".join(masked)
    for m in AMOUNT_RE.finditer(text):
        val = parse_amount(m.group(0))
        if val is not None:
            out.append((val, m.start(), m.end()))
    return sorted(out, key=lambda x: x[1])


def _mk_date(y: int, m: int, d: int) -> date | None:
    if y < 100:
        y += 2000
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str, order: str = "MDY") -> list[tuple[date, bool, int, int]]:
    """Find dates in text. Returns (date, ambiguous, start, end)."""
    out: list[tuple[date, bool, int, int]] = []
    for i, pat in enumerate(DATE_PATTERNS):
        for m in pat.finditer(text):
            g = m.groups()
            amb = False
            if i == 0:
                d = _mk_date(int(g[0]), int(g[1]), int(g[2]))
            elif i == 1:
                a, b, y = int(g[0]), int(g[1]), int(g[2])
                if a > 12 and b <= 12:
                    d = _mk_date(y, b, a)
                elif b > 12 and a <= 12:
                    d = _mk_date(y, a, b)
                else:
                    amb = a != b
                    d = _mk_date(y, a, b) if order == "MDY" else _mk_date(y, b, a)
            elif i == 2:
                d = _mk_date(int(g[2]), MONTHS[g[1].lower()], int(g[0]))
            else:
                d = _mk_date(int(g[2]), MONTHS[g[0].lower()], int(g[1]))
            if d and not any(s <= m.start() < e for _, _, s, e in out):
                out.append((d, amb, m.start(), m.end()))
    return sorted(out, key=lambda x: x[2])


def parse_date(raw, order: str = "MDY") -> tuple[date | None, bool]:
    if raw is None:
        return None, False
    if isinstance(raw, date):
        return raw, False
    found = find_dates(str(raw), order)
    if found:
        return found[0][0], found[0][1]
    return None, False


def detect_currency(text: str) -> tuple[str | None, str | None]:
    """Return (currency_code, evidence_string)."""
    codes = re.findall(r"\b(" + "|".join(CURRENCY_CODES) + r")\b", text)
    if codes:
        best = max(set(codes), key=codes.count)
        return best, best
    for sym, code in CURRENCY_SYMBOLS.items():
        if sym in text:
            return code, sym
    low = text.lower()
    for word, code in CURRENCY_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            return code, word
    return None, None


def norm_invoice_number(s: str | None) -> str | None:
    if not s:
        return None
    n = re.sub(r"[^A-Za-z0-9]", "", str(s)).upper()
    return n or None


_SUFFIXES = r"\b(inc|incorporated|llc|ltd|limited|co|corp|corporation|company|plc|pvt|gmbh|llp)\b\.?"


def norm_name(s: str | None) -> str | None:
    if not s:
        return None
    n = re.sub(r"[^a-z0-9 ]", " ", str(s).lower())
    n = re.sub(_SUFFIXES, " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n or None


def to_float(v) -> float | None:
    d = parse_amount(v)
    return float(d) if d is not None else None
