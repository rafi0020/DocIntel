"""Job queue (Redis + RQ). One job per document, retried with back-off."""
from __future__ import annotations

import logging
from functools import lru_cache

from ..config import get_settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _queue():
    from redis import Redis
    from rq import Queue

    s = get_settings()
    return Queue(s.queue_name, connection=Redis.from_url(s.redis_url), default_timeout=s.job_timeout_s)


def enqueue_document(document_id: str) -> str | None:
    s = get_settings()
    if s.queue_sync:
        from .tasks import process_document_job

        try:
            process_document_job(str(document_id))
        except Exception:  # noqa: BLE001 - recorded on the document already
            log.exception("inline processing failed")
        return None
    from rq import Retry

    job = _queue().enqueue(
        "app.worker.tasks.process_document_job",
        str(document_id),
        retry=Retry(max=s.job_retries, interval=[10, 60]),
        job_timeout=s.job_timeout_s,
        result_ttl=3600,
        failure_ttl=7 * 24 * 3600,
    )
    return job.id


def queue_health() -> dict:
    s = get_settings()
    if s.queue_sync:
        return {"mode": "inline", "ok": True}
    try:
        q = _queue()
        q.connection.ping()
        from rq import Worker

        return {"mode": "redis", "ok": True, "queued": q.count, "workers": len(Worker.all(queue=q))}
    except Exception as e:  # noqa: BLE001
        return {"mode": "redis", "ok": False, "error": str(e)}
