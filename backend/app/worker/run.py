"""Start N RQ worker processes.

Each process is an RQ SimpleWorker: jobs run in the worker process itself
instead of a fork per job. Models (embeddings, OCR) load once per process and
stay warm; ONNX Runtime thread pools do not survive fork(), so forking after
loading them made inference ~50x slower. Job timeouts are still enforced.

    python -m app.worker.run --workers 2
"""
from __future__ import annotations

import argparse
import logging
import multiprocessing as mp

from ..config import get_settings


def _preload():
    from ..search.embed import embed

    embed(["warm up"])


def _work(name: str):
    from redis import Redis
    from rq import Queue, SimpleWorker

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _preload()
    s = get_settings()
    conn = Redis.from_url(s.redis_url)
    SimpleWorker([Queue(s.queue_name, connection=conn)], connection=conn, name=name).work(with_scheduler=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from ..db import init_db

    init_db()
    import socket
    import uuid

    # unique per start: in containers the PID is always 1, and a killed container
    # can leave its worker registration behind in Redis for a while
    procs = [mp.Process(target=_work, args=(f"{socket.gethostname()}-{i}-{uuid.uuid4().hex[:6]}",), daemon=False)
             for i in range(a.workers)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()


if __name__ == "__main__":
    main()
