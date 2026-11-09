"""The document pipeline, independent of the database.

ingest -> split into invoices -> extract (rules + LLM, provenance-checked)
       -> single-record validation

The background worker calls this and persists the result; the evaluation
runner calls exactly the same function, so measured accuracy is the accuracy
of the shipped code path.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..extraction.extractor import extract_from_pages
from ..extraction.llm import get_llm
from ..extraction.schema import ExtractedInvoice
from ..extraction.spreadsheet import extract_sheet
from ..runtime_settings import effective_settings
from ..validation.rules import Issue, validate_record
from .doc_types import IngestResult
from .ingest import ProgressFn, ingest
from .segment import split_invoices


@dataclass
class ProcessedRecord:
    invoice: ExtractedInvoice
    issues: list[Issue]


@dataclass
class ProcessOutput:
    ingest: IngestResult
    records: list[ProcessedRecord]
    timings_ms: dict[str, int] = field(default_factory=dict)
    extractor: str = "rules"


def process_document(data: bytes, filename: str, progress: ProgressFn | None = None, use_llm: bool = True) -> ProcessOutput:
    s = effective_settings()
    timings: dict[str, int] = {}
    t0 = time.perf_counter()
    ing = ingest(data, filename, progress)
    timings["ingest"] = int((time.perf_counter() - t0) * 1000)
    if progress:
        progress(0.7, "extracting")

    llm = get_llm() if use_llm else None
    t1 = time.perf_counter()
    invoices: list[ExtractedInvoice] = []
    if ing.source_kind == "spreadsheet":
        for page in ing.pages:
            recs = extract_sheet(page)
            if recs is None:  # form-like sheet: treat as a text document
                inv = extract_from_pages([page], llm)
                if inv.value("invoice_number") is None and inv.value("total") is None:
                    continue  # cover / notes sheet with no invoice on it
                inv.sheet_name = page.label
                inv.fields = {k: _sheetify(v, page.label) for k, v in inv.fields.items()}
                invoices.append(inv)
            else:
                invoices.extend(recs)
    else:
        segments = split_invoices(ing.pages)
        workers = max(1, s.llm_concurrency if llm else 1)
        if len(segments) == 1 or workers == 1:
            for i, seg in enumerate(segments):
                invoices.append(extract_from_pages(seg.pages, llm))
                if progress and len(segments) > 1:
                    progress(0.7 + 0.25 * (i + 1) / len(segments), "extracting")
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [pool.submit(extract_from_pages, seg.pages, llm) for seg in segments]
                for i, f in enumerate(futs):
                    invoices.append(f.result())
                    if progress:
                        progress(0.7 + 0.25 * (i + 1) / len(segments), "extracting")
    timings["extract"] = int((time.perf_counter() - t1) * 1000)

    t2 = time.perf_counter()
    records = [ProcessedRecord(inv, validate_record(inv, s)) for inv in invoices]
    timings["validate"] = int((time.perf_counter() - t2) * 1000)
    timings["total"] = int((time.perf_counter() - t0) * 1000)
    extractor = next((i.extractor for i in invoices if i.extractor.startswith("hybrid")), invoices[0].extractor if invoices else "rules")
    return ProcessOutput(ing, records, timings, extractor)


def _sheetify(fv, sheet):
    # Text-extracted spreadsheet values have no page boxes; point at the sheet instead.
    if fv.source and "page" in fv.source:
        fv.source = {"sheet": sheet}
    return fv
