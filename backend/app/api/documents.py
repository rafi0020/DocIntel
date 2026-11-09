from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..auth import Principal, audit, need
from ..config import get_settings
from ..db import get_session
from ..models import Document, Invoice, Page
from ..security import extension_ok, safe_filename
from ..worker.queue import enqueue_document
from .serializers import doc_summary, event_json, invoice_json

router = APIRouter(prefix="/api/documents", tags=["documents"])
CHUNK = 1024 * 1024


def _get_doc(session: Session, doc_id: uuid.UUID) -> Document:
    doc = session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


@router.post("", status_code=status.HTTP_202_ACCEPTED, summary="Upload one or more documents")
async def upload(request: Request, files: list[UploadFile] = File(...), session: Session = Depends(get_session),
                 principal: Principal = Depends(need("reviewer"))):
    s = get_settings()
    if not files:
        raise HTTPException(400, "No files supplied")
    if len(files) > s.max_files_per_upload:
        raise HTTPException(400, f"At most {s.max_files_per_upload} files per request")
    limit = s.max_upload_mb * 1024 * 1024
    created, rejected = [], []
    for up in files:
        name = safe_filename(up.filename or "upload")
        if not extension_ok(name):
            rejected.append({"filename": name, "reason": "unsupported file type (allowed: PDF, JPG, PNG, TIFF, XLSX, XLS, CSV)"})
            continue
        doc_id = uuid.uuid4()
        ext = name.rsplit(".", 1)[-1].lower()
        folder = s.uploads_dir / str(doc_id)
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"original.{ext}"
        h, size, too_big = hashlib.sha256(), 0, False
        with dest.open("wb") as fh:
            while chunk := await up.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    too_big = True
                    break
                h.update(chunk)
                fh.write(chunk)
        if too_big:
            dest.unlink(missing_ok=True)
            rejected.append({"filename": name, "reason": f"larger than {s.max_upload_mb} MB"})
            continue
        doc = Document(id=doc_id, filename=name, file_type="jpg" if ext == "jpeg" else ("tiff" if ext == "tif" else ext),
                       mime_type=up.content_type, size_bytes=size, sha256=h.hexdigest(), storage_path=str(dest), status="queued",
                       stage="queued", progress=0.0, uploaded_by_id=principal.id)
        session.add(doc)
        audit(session, principal, "document.upload", "document", doc_id, {"filename": name, "size": size}, request)
        session.commit()
        created.append(doc)
    for doc in created:
        enqueue_document(str(doc.id))
    for doc in created:
        session.refresh(doc)
    return {"documents": [doc_summary(d) for d in created], "rejected": rejected}


@router.get("", summary="List documents")
def list_documents(
    status_: str | None = Query(None, alias="status"),
    q: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    session: Session = Depends(get_session),
):
    stmt = select(Document)
    if status_:
        stmt = stmt.where(Document.status.in_(status_.split(",")))
    if q:
        stmt = stmt.where(Document.filename.ilike(f"%{q}%"))
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    docs = session.scalars(stmt.order_by(Document.created_at.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "documents": [doc_summary(d) for d in docs]}


@router.get("/status", summary="Batch status polling for many documents")
def batch_status(ids: str = Query(..., description="comma-separated document ids"), session: Session = Depends(get_session)):
    try:
        id_list = [uuid.UUID(i) for i in ids.split(",") if i][:200]
    except ValueError:
        raise HTTPException(400, "invalid id") from None
    docs = session.scalars(select(Document).where(Document.id.in_(id_list))).all()
    return {"documents": [doc_summary(d) for d in docs]}


@router.post("/reprocess-failed", summary="Re-queue every failed document")
def reprocess_failed(request: Request, session: Session = Depends(get_session), principal: Principal = Depends(need("reviewer"))):
    docs = session.scalars(select(Document).where(Document.status == "failed")).all()
    for d in docs:
        d.status, d.stage, d.progress, d.error_code, d.error_message = "queued", "queued", 0.0, None, None
    if docs:
        audit(session, principal, "document.reprocess_failed", "document", None, {"count": len(docs)}, request)
    session.commit()
    for d in docs:
        enqueue_document(str(d.id))
    return {"requeued": [str(d.id) for d in docs]}


@router.get("/{doc_id}", summary="Document detail with records and processing history")
def get_document(doc_id: uuid.UUID, session: Session = Depends(get_session)):
    doc = session.scalars(
        select(Document).where(Document.id == doc_id).options(selectinload(Document.invoices).selectinload(Invoice.issues))
    ).first()
    if doc is None:
        raise HTTPException(404, "Document not found")
    pages = session.execute(
        select(Page.page_no, Page.label, Page.method, Page.ocr_confidence, Page.width, Page.height, Page.error)
        .where(Page.document_id == doc_id).order_by(Page.page_no)
    ).all()
    return {
        **doc_summary(doc),
        "pages": [{"page_no": p.page_no, "label": p.label, "method": p.method, "ocr_confidence": p.ocr_confidence,
                   "width": p.width, "height": p.height, "error": p.error} for p in pages],
        "invoices": [invoice_json(i, full=False) for i in doc.invoices],
        "events": [event_json(e) for e in doc.events],
    }


@router.get("/{doc_id}/status", summary="Processing status of one document")
def get_status(doc_id: uuid.UUID, session: Session = Depends(get_session)):
    return doc_summary(_get_doc(session, doc_id))


@router.get("/{doc_id}/results", summary="Extracted, validated records (structured JSON)")
def get_results(doc_id: uuid.UUID, session: Session = Depends(get_session)):
    doc = _get_doc(session, doc_id)
    if doc.status in ("queued", "processing"):
        raise HTTPException(409, f"Document is still {doc.status}")
    return {"document": doc_summary(doc), "records": [invoice_json(i) for i in doc.invoices]}


@router.get("/{doc_id}/pages/{page_no}", summary="Text and word boxes of one page / sheet rows")
def get_page(doc_id: uuid.UUID, page_no: int, session: Session = Depends(get_session)):
    p = session.scalars(select(Page).where(Page.document_id == doc_id, Page.page_no == page_no)).first()
    if p is None:
        raise HTTPException(404, "Page not found")
    return {"page_no": p.page_no, "label": p.label, "method": p.method, "ocr_confidence": p.ocr_confidence,
            "text": p.text, "layout": p.layout, "width": p.width, "height": p.height, "error": p.error}


@router.get("/{doc_id}/pages/{page_no}/image", summary="Rendered page image (PNG)")
def page_image(doc_id: uuid.UUID, page_no: int, session: Session = Depends(get_session)):
    s = get_settings()
    doc = _get_doc(session, doc_id)
    if doc.file_type in ("xlsx", "xls", "csv"):
        raise HTTPException(400, "Spreadsheets have no page images; use the page rows instead")
    cache = s.cache_dir / str(doc.id) / f"p{page_no}.png"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        try:
            cache.write_bytes(_render_page(Path(doc.storage_path), doc.file_type, page_no))
        except IndexError:
            raise HTTPException(404, "Page not found") from None
        except Exception as e:  # noqa: BLE001
            raise HTTPException(422, f"Page cannot be rendered: {e}") from None
    return FileResponse(cache, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


def _render_page(path: Path, file_type: str, page_no: int) -> bytes:
    if file_type == "pdf":
        import pymupdf

        doc = pymupdf.open(path)
        if page_no < 1 or page_no > doc.page_count:
            raise IndexError
        return doc[page_no - 1].get_pixmap(dpi=110).tobytes("png")
    from PIL import Image, ImageSequence

    im = Image.open(path)
    frames = list(ImageSequence.Iterator(im))
    if page_no < 1 or page_no > len(frames):
        raise IndexError
    fr = frames[page_no - 1].convert("RGB")
    if fr.width > 1600:
        fr = fr.resize((1600, int(fr.height * 1600 / fr.width)))
    buf = io.BytesIO()
    fr.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@router.get("/{doc_id}/file", summary="Download the original file")
def download(doc_id: uuid.UUID, session: Session = Depends(get_session)):
    doc = _get_doc(session, doc_id)
    return FileResponse(doc.storage_path, filename=doc.filename, media_type=doc.mime_type or "application/octet-stream")


@router.post("/{doc_id}/reprocess", summary="Re-run processing (failed jobs, or force for any document)")
def reprocess(doc_id: uuid.UUID, request: Request, force: bool = False, session: Session = Depends(get_session),
              principal: Principal = Depends(need("reviewer"))):
    doc = _get_doc(session, doc_id)
    if doc.status in ("queued", "processing"):
        raise HTTPException(409, "Document is already queued or processing")
    if doc.status != "failed" and not force:
        raise HTTPException(409, "Only failed documents are re-processed unless force=true")
    doc.status, doc.stage, doc.progress, doc.error_code, doc.error_message = "queued", "queued", 0.0, None, None
    audit(session, principal, "document.reprocess", "document", doc.id, {"filename": doc.filename, "force": force}, request)
    session.commit()
    enqueue_document(str(doc.id))
    session.refresh(doc)
    return doc_summary(doc)


@router.delete("/{doc_id}", status_code=204, summary="Delete a document and its results")
def delete_document(doc_id: uuid.UUID, request: Request, session: Session = Depends(get_session),
                    principal: Principal = Depends(need("reviewer"))):
    doc = _get_doc(session, doc_id)
    _check_can_delete(doc, principal)
    _remove(session, doc, principal, request)
    session.commit()
    return Response(status_code=204)


def _check_can_delete(doc: Document, principal: Principal) -> None:
    if not principal.can("admin") and doc.uploaded_by_id != principal.id:
        raise HTTPException(403, "Only the uploader or an administrator can delete this document.")


def _remove(session: Session, doc: Document, principal: Principal, request: Request) -> None:
    import shutil

    s = get_settings()
    audit(session, principal, "document.delete", "document", doc.id, {"filename": doc.filename}, request)
    doc_id = doc.id
    session.delete(doc)
    shutil.rmtree(s.uploads_dir / str(doc_id), ignore_errors=True)
    shutil.rmtree(s.cache_dir / str(doc_id), ignore_errors=True)


class BulkIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    action: str = Field(pattern="^(reprocess|delete)$")


@router.post("/bulk", summary="Apply one action to many documents (reprocess or delete)")
def bulk(body: BulkIn, request: Request, session: Session = Depends(get_session), principal: Principal = Depends(need("reviewer"))):
    docs = session.scalars(select(Document).where(Document.id.in_(body.ids))).all()
    done, skipped = [], []
    for d in docs:
        if body.action == "delete":
            if not principal.can("admin") and d.uploaded_by_id != principal.id:
                skipped.append({"id": str(d.id), "reason": "not the uploader"})
                continue
            _remove(session, d, principal, request)
        else:
            if d.status in ("queued", "processing"):
                skipped.append({"id": str(d.id), "reason": f"already {d.status}"})
                continue
            d.status, d.stage, d.progress, d.error_code, d.error_message = "queued", "queued", 0.0, None, None
            audit(session, principal, "document.reprocess", "document", d.id, {"filename": d.filename, "bulk": True}, request)
        done.append(str(d.id))
    session.commit()
    if body.action == "reprocess":
        for i in done:
            enqueue_document(i)
    return {"done": done, "skipped": skipped, "missing": len(body.ids) - len(docs)}
