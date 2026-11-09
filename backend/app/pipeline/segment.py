"""Split a multi-invoice PDF (e.g. a 1000-page batch scan) into single invoices.

A new invoice starts on a page that
  * prints an invoice number different from the current invoice's, or
  * says "Page 1 of N" while the current invoice already has pages.
Pages with no number (continuation pages, blank pages) stay with the current
invoice. Cheap and deterministic, so it scales to thousands of pages.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..extraction.normalize import norm_invoice_number
from ..extraction.rules import _INV_LABEL
from .doc_types import PageContent

_PAGE_OF = re.compile(r"\bpage\s+(\d+)\s*(?:of|/)\s*(\d+)\b", re.I)


@dataclass
class Segment:
    pages: list[PageContent] = field(default_factory=list)
    number: str | None = None


def _page_number(p: PageContent) -> str | None:
    for ln in p.text.splitlines()[:40]:
        m = _INV_LABEL.search(ln)
        if m:
            return norm_invoice_number(m.group("val"))
    return None


def split_invoices(pages: list[PageContent]) -> list[Segment]:
    segments: list[Segment] = []
    cur: Segment | None = None
    for p in pages:
        num = _page_number(p)
        pm = _PAGE_OF.search(p.text)
        first_of_n = pm is not None and pm.group(1) == "1"
        new = (
            cur is None
            or (num is not None and cur.number is not None and num != cur.number)
            or (first_of_n and len(cur.pages) > 0 and (num is None or num != cur.number))
        )
        if new:
            cur = Segment(number=num)
            segments.append(cur)
        elif cur.number is None and num is not None:
            cur.number = num
        cur.pages.append(p)
    return segments
