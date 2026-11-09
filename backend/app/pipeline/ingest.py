"""File ingestion: sniff the real file type, then route to the right reader.

* Digital PDF pages  -> PyMuPDF text layer with word boxes (fast, exact)
* Scanned PDF pages  -> rendered at OCR_DPI and OCR'd (page-level fallback, so
                        mixed PDFs work: only pages without a text layer are OCR'd)
* JPG / PNG / TIFF   -> OCR (multi-frame TIFFs become multiple pages)
* XLSX / XLS / CSV   -> every sheet parsed to a grid of strings

Failures are raised as IngestError with a stable code so the API/UI can show a
clear reason instead of a stack trace. Single bad pages are recorded on the page
and do not fail the whole document.
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from ..config import get_settings
from .doc_types import IngestError, IngestResult, PageContent, Word
from .ocr import assign_lines, ocr_image, words_to_text

log = logging.getLogger(__name__)

SUPPORTED = {"pdf", "png", "jpg", "jpeg", "tif", "tiff", "xlsx", "xls", "csv"}
ProgressFn = Callable[[float, str], None]


def sniff_type(data: bytes, filename: str) -> str:
    """Determine the file type from magic bytes, falling back to the extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not data:
        raise IngestError("empty_file", "The file is empty (0 bytes).")
    head = data[:8]
    if data[:1024].lstrip().startswith(b"%PDF") or head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\x89PNG"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if any(n.startswith("xl/") for n in z.namelist()):
                    return "xlsx"
        except zipfile.BadZipFile as e:
            raise IngestError("corrupted_file", "The spreadsheet archive is damaged and cannot be opened.") from e
        raise IngestError("unsupported_type", "ZIP archive is not an Excel workbook.")
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "xls"
    if ext == "csv":
        return "csv"
    # Extension says a binary format but the bytes don't match -> damaged file.
    if ext in SUPPORTED:
        raise IngestError("corrupted_file", f"File content does not match a valid .{ext} file (damaged or mislabelled).")
    raise IngestError("unsupported_type", f"Unsupported file type '{ext or 'unknown'}'.")


# --------------------------------------------------------------------------- PDF
def _pdf_words(page) -> list[Word]:
    w, h = page.rect.width, page.rect.height
    raw = page.get_text("words", sort=True)  # x0,y0,x1,y1,word,block,line,wno
    words = [Word(t, (x0 / w, y0 / h, x1 / w, y1 / h), 1.0) for x0, y0, x1, y1, t, *_ in raw]
    # Group by geometry, not by PDF text blocks: many generators emit each table
    # cell as its own block, which would otherwise split one table row into lines.
    return assign_lines(words)


def _render(page, dpi: int) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return img[:, :, ::-1].copy() if pix.n == 3 else img.copy()  # RGB -> BGR


def ingest_pdf(data: bytes, progress: ProgressFn | None = None) -> IngestResult:
    import pymupdf

    s = get_settings()
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        raise IngestError("corrupted_file", f"PDF could not be opened: {e}") from e
    if doc.needs_pass:
        raise IngestError("encrypted_pdf", "PDF is password protected.")
    n = doc.page_count
    if n == 0:
        raise IngestError("empty_document", "PDF has no pages.")
    if n > s.max_pages:
        raise IngestError("too_many_pages", f"PDF has {n} pages; the limit is {s.max_pages}.")

    pages: list[PageContent | None] = [None] * n
    to_ocr: list[int] = []
    for i in range(n):
        try:
            page = doc[i]
            words = _pdf_words(page)
            text = words_to_text_pdf(words)
            if len(text.replace(" ", "").strip()) >= s.min_text_chars_per_page:
                pages[i] = PageContent(i + 1, "text", text, words, page.rect.width, page.rect.height)
            else:
                to_ocr.append(i)
        except Exception as e:  # noqa: BLE001 - keep going, record per-page error
            log.warning("page %s failed: %s", i + 1, e)
            pages[i] = PageContent(i + 1, "text", "", [], error=f"page_unreadable: {e}")
        if progress and i % 25 == 0:
            progress(0.3 * (i + 1) / n, "reading pdf")

    # OCR scanned pages in batches. Rendering stays on this thread (PyMuPDF is not
    # thread-safe); recognition runs in a pool (ONNX Runtime releases the GIL).
    if to_ocr:
        batch = max(1, s.ocr_threads * 2)
        with ThreadPoolExecutor(max_workers=s.ocr_threads) as pool:
            for start in range(0, len(to_ocr), batch):
                chunk = to_ocr[start : start + batch]
                imgs = []
                for i in chunk:
                    try:
                        imgs.append((i, _render(doc[i], s.ocr_dpi)))
                    except Exception as e:  # noqa: BLE001
                        pages[i] = PageContent(i + 1, "ocr", "", [], error=f"render_failed: {e}")
                futures = {i: pool.submit(ocr_image, img) for i, img in imgs}
                for i, fut in futures.items():
                    page = doc[i]
                    try:
                        words, conf = fut.result()
                        pages[i] = PageContent(
                            i + 1, "ocr", words_to_text(words), words, page.rect.width, page.rect.height, conf
                        )
                    except Exception as e:  # noqa: BLE001
                        pages[i] = PageContent(i + 1, "ocr", "", [], error=f"ocr_failed: {e}")
                if progress:
                    progress(0.3 + 0.4 * min(1.0, (start + len(chunk)) / len(to_ocr)), "ocr")

    final = [p for p in pages if p is not None]
    ocr_n = sum(1 for p in final if p.method == "ocr")
    kind = "digital_pdf" if ocr_n == 0 else ("scanned_pdf" if ocr_n == n else "mixed_pdf")
    if all(not p.text.strip() for p in final):
        raise IngestError("no_text_found", "No readable text found on any page (blank or unreadable scan).")
    return IngestResult("pdf", kind, final)


def words_to_text_pdf(words: list[Word]) -> str:
    """Rebuild text lines from PDF words, keeping wide gaps as column breaks."""
    return words_to_text(words)


# ------------------------------------------------------------------------ images
def ingest_image(data: bytes, file_type: str, progress: ProgressFn | None = None) -> IngestResult:
    from PIL import Image, ImageSequence, UnidentifiedImageError

    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise IngestError("corrupted_file", f"Image could not be decoded: {e}") from e

    frames = []
    try:
        for fr in ImageSequence.Iterator(im):
            frames.append(np.array(fr.convert("RGB"))[:, :, ::-1].copy())
    except OSError as e:
        if not frames:
            raise IngestError("corrupted_file", f"Image data is truncated: {e}") from e

    pages = []
    for i, img in enumerate(frames):
        h, w = img.shape[:2]
        words, conf = ocr_image(img)
        pages.append(PageContent(i + 1, "ocr", words_to_text(words), words, float(w), float(h), conf))
        if progress:
            progress(0.7 * (i + 1) / len(frames), "ocr")
    if all(not p.text.strip() for p in pages):
        raise IngestError("no_text_found", "OCR found no text in the image.")
    return IngestResult(file_type, "image", pages)


# ------------------------------------------------------------------ spreadsheets
def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if np.isnan(v):
            return ""
        return f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    return str(v).strip()


def _sheet_page(idx: int, name: str, rows: list[list[str]]) -> PageContent | None:
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return None
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    # Drop fully empty columns
    keep = [j for j in range(width) if any(r[j] for r in rows)]
    rows = [[r[j] for j in keep] for r in rows]
    text = "\n".join("   ".join(c for c in r if c) for r in rows)
    return PageContent(idx, "table", text, [], label=name, table=rows)


def ingest_spreadsheet(data: bytes, file_type: str) -> IngestResult:
    import pandas as pd

    pages: list[PageContent] = []
    warnings: list[str] = []
    if file_type == "csv":
        text = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None or "\x00" in text[:2000]:
            raise IngestError("corrupted_file", "CSV is not valid text.")
        try:
            dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t|")
            delim = dialect.delimiter
        except csv.Error:
            delim = ","
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim)]
        p = _sheet_page(1, "csv", rows)
        if p:
            pages.append(p)
    else:
        engine = "openpyxl" if file_type == "xlsx" else "xlrd"
        try:
            sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, engine=engine, dtype=object)
        except Exception as e:  # noqa: BLE001
            raise IngestError("corrupted_file", f"Workbook could not be read: {e}") from e
        for i, (name, df) in enumerate(sheets.items()):
            rows = [[_cell(v) for v in row] for row in df.itertuples(index=False, name=None)]
            p = _sheet_page(i + 1, str(name), rows)
            if p:
                pages.append(p)
            else:
                warnings.append(f"sheet '{name}' is empty")
    if not pages:
        raise IngestError("empty_document", "Spreadsheet contains no data.")
    for i, p in enumerate(pages):
        p.page_no = i + 1
    return IngestResult(file_type, "spreadsheet", pages, warnings)


# ---------------------------------------------------------------------- dispatch
def ingest(data: bytes, filename: str, progress: ProgressFn | None = None) -> IngestResult:
    ftype = sniff_type(data, filename)
    if ftype == "pdf":
        return ingest_pdf(data, progress)
    if ftype in ("png", "jpg", "tiff"):
        return ingest_image(data, ftype, progress)
    if ftype in ("xlsx", "xls", "csv"):
        return ingest_spreadsheet(data, ftype)
    raise IngestError("unsupported_type", f"Unsupported file type {ftype}")
