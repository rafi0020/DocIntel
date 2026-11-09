"""OCR for scanned pages and photos.

Two engines behind one function: Tesseract (the default) and RapidOCR (PP-OCR
models on ONNX Runtime), selected with OCR_ENGINE. Images are cleaned up before
OCR: upscaling of low-resolution input, deskew, contrast equalisation and light
denoising.
"""
from __future__ import annotations

import threading
from functools import lru_cache

import cv2
import numpy as np

from .doc_types import Word

_lock = threading.Lock()


@lru_cache(maxsize=1)
def _rapidocr():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def _estimate_skew(gray: np.ndarray) -> float:
    """Return the dominant text angle in degrees (small angles only)."""
    inv = cv2.bitwise_not(gray)
    thresh = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) < 500:
        return 0.0
    # Use horizontal-ish lines found by a Hough transform: more stable than minAreaRect
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=120, minLineLength=gray.shape[1] // 6, maxLineGap=12)
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        if x2 == x1:
            continue
        a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(a) < 10:
            angles.append(a)
    if not angles:
        return 0.0
    return float(np.median(angles))


def preprocess(img: np.ndarray) -> np.ndarray:
    """Normalise a page image for OCR. Returns a 3-channel uint8 image."""
    if img.ndim == 2:
        gray = img
    elif img.shape[2] == 4:
        gray = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    else:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Upscale small images: OCR models struggle below ~1200px page width.
    h, w = gray.shape
    if w < 1200:
        scale = 1600 / w
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    angle = _estimate_skew(gray)
    if 0.3 < abs(angle) < 10:
        h, w = gray.shape
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        gray = cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)

    # Mild denoise + local contrast. Kept conservative: aggressive binarisation hurts
    # the neural recogniser more than it helps.
    gray = cv2.medianBlur(gray, 3)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def assign_lines(words: list[Word]) -> list[Word]:
    """Group boxes into reading-order lines by vertical overlap."""
    words = sorted(words, key=lambda w: ((w.box[1] + w.box[3]) / 2, w.box[0]))
    lines: list[list[Word]] = []
    for w in words:
        cy = (w.box[1] + w.box[3]) / 2
        h = w.box[3] - w.box[1]
        placed = False
        if lines:
            last = lines[-1]
            ly0 = min(x.box[1] for x in last)
            ly1 = max(x.box[3] for x in last)
            lc = (ly0 + ly1) / 2
            if abs(cy - lc) < max(h, ly1 - ly0) * 0.5:
                last.append(w)
                placed = True
        if not placed:
            lines.append([w])
    out: list[Word] = []
    for i, line in enumerate(lines):
        for w in sorted(line, key=lambda x: x.box[0]):
            w.line = i
            out.append(w)
    return out


def words_to_text(words: list[Word]) -> str:
    lines: dict[int, list[Word]] = {}
    for w in words:
        lines.setdefault(w.line, []).append(w)
    out = []
    for i in sorted(lines):
        row = sorted(lines[i], key=lambda x: x.box[0])
        # Preserve big horizontal gaps as column separators: helps table parsing.
        parts = [row[0].text]
        for a, b in zip(row, row[1:], strict=False):
            gap = b.box[0] - a.box[2]
            parts.append("   " if gap > 0.03 else " ")
            parts.append(b.text)
        out.append("".join(parts))
    return "\n".join(out)


def ocr_image(img: np.ndarray, engine: str | None = None) -> tuple[list[Word], float | None]:
    """OCR a BGR/gray image. Returns words (normalised boxes) and mean confidence."""
    from ..runtime_settings import effective_settings

    engine = engine or effective_settings().ocr_engine
    proc = preprocess(img)
    h, w = proc.shape[:2]
    words: list[Word] = []

    if engine == "tesseract":
        import pytesseract

        data = pytesseract.image_to_data(proc, output_type=pytesseract.Output.DICT, config="--psm 6")
        for i, txt in enumerate(data["text"]):
            txt = (txt or "").strip()
            conf = float(data["conf"][i])
            if not txt or conf < 0:
                continue
            x, y, bw, bh = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            words.append(Word(txt, (x / w, y / h, (x + bw) / w, (y + bh) / h), conf / 100.0))
    else:
        result, _ = _rapidocr()(proc)
        for box, txt, score in result or []:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            words.append(
                Word(str(txt).strip(), (min(xs) / w, min(ys) / h, max(xs) / w, max(ys) / h), float(score))
            )

    words = [x for x in words if x.text]
    words = assign_lines(words)
    conf = float(np.mean([x.conf for x in words])) if words else None
    return words, conf


def decode_image(data: bytes) -> np.ndarray | None:
    arr = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)
