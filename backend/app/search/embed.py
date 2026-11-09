"""Text embeddings for semantic search (local ONNX model, no API calls)."""
from __future__ import annotations

import logging
import threading
from functools import lru_cache

from ..config import get_settings

log = logging.getLogger(__name__)
_lock = threading.Lock()


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    s = get_settings()
    return TextEmbedding(s.embedding_model, cache_dir=str(s.model_dir or (s.storage_dir / "models")))


def embed(texts: list[str]) -> list[list[float]] | None:
    s = get_settings()
    if not s.embeddings_enabled or not texts:
        return None
    try:
        with _lock:
            return [v.tolist() for v in _model().embed(texts)]
    except Exception as e:  # noqa: BLE001 - search degrades to keyword-only
        log.warning("embedding failed: %s", e)
        return None


def invoice_search_text(fields: dict, items: list[dict], raw_text: str, filename: str) -> tuple[str, str]:
    """Returns (keyword_text, semantic_text)."""
    v = {k: (f.get("value") if isinstance(f, dict) else f) for k, f in fields.items()}
    descs = "; ".join(str(i.get("description")) for i in items if i.get("description"))
    semantic = (
        f"Invoice {v.get('invoice_number') or ''} from {v.get('supplier_name') or 'unknown supplier'} "
        f"to {v.get('customer_name') or 'unknown customer'} dated {v.get('invoice_date') or 'unknown'}, "
        f"total {v.get('total') or ''} {v.get('currency') or ''}. Items: {descs}"
    )
    keyword = f"{filename} {semantic} {raw_text[:6000]}"
    return keyword, semantic[:2000]
