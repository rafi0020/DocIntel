from __future__ import annotations

from dataclasses import dataclass, field


class IngestError(Exception):
    """A file-level failure with a stable, machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Word:
    text: str
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 normalised to 0..1
    conf: float = 1.0
    line: int = 0  # reading-order line index within the page

    def to_json(self) -> dict:
        return {"t": self.text, "b": [round(v, 4) for v in self.box], "c": round(self.conf, 3), "l": self.line}


@dataclass
class PageContent:
    page_no: int
    method: str  # text | ocr | table
    text: str = ""
    words: list[Word] = field(default_factory=list)
    width: float | None = None
    height: float | None = None
    ocr_confidence: float | None = None
    label: str | None = None  # sheet name
    table: list[list[str]] | None = None  # spreadsheet rows (as strings)
    error: str | None = None

    def layout_json(self) -> dict:
        if self.table is not None:
            return {"rows": self.table[:5000]}
        return {"words": [w.to_json() for w in self.words]}


@dataclass
class IngestResult:
    file_type: str
    source_kind: str  # digital_pdf | scanned_pdf | mixed_pdf | image | spreadsheet
    pages: list[PageContent]
    warnings: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\f\n".join(p.text for p in self.pages)
