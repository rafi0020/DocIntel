"""Upload the files in ./samples to a running DocIntel API and wait for processing.

    python scripts/seed_demo.py [--api http://localhost:8000] [--email E --password P | --api-key KEY]

Signs in as the demo reviewer by default (see "Demo accounts" in the README). Uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "samples"
EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".xlsx", ".xls", ".csv"}


def request(url: str, auth: dict, data: bytes | None = None, ctype: str | None = None):
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if ctype:
        req.add_header("Content-Type", ctype)
    for k, v in auth.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--api-key", help="service API key (API_KEY in .env) instead of a user account")
    ap.add_argument("--email", default="reviewer@docintel.demo")
    ap.add_argument("--password", default="Reviewer#Demo2026")
    a = ap.parse_args()
    if a.api_key:
        auth = {"X-API-Key": a.api_key}
    else:
        body = json.dumps({"email": a.email, "password": a.password}).encode()
        token = request(f"{a.api}/api/auth/login", {}, body, "application/json")["token"]
        auth = {"Authorization": f"Bearer {token}"}
    files = sorted(p for p in ROOT.iterdir() if p.suffix.lower() in EXTS)
    # invoices first, then the re-sent duplicates and the ledgers, so the
    # duplicate and ledger cross-checks have something to compare against
    files.sort(key=lambda p: (p.name.startswith("dup_"), p.name.startswith("ledger"), p.name))
    ids = []
    for group in (files[i : i + 8] for i in range(0, len(files), 8)):
        boundary = uuid.uuid4().hex
        body = b""
        for p in group:
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{p.name}\"\r\n"
                     f"Content-Type: {ctype}\r\n\r\n").encode() + p.read_bytes() + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        res = request(f"{a.api}/api/documents", auth, body, f"multipart/form-data; boundary={boundary}")
        ids += [d["id"] for d in res["documents"]]
        print(f"uploaded {len(res['documents'])} files")
        time.sleep(2)  # let earlier groups finish so cross-document checks see them
    while True:
        docs = request(f"{a.api}/api/documents/status?ids={','.join(ids)}", auth)["documents"]
        busy = [d for d in docs if d["status"] in ("queued", "processing")]
        print(f"\r{len(docs) - len(busy)}/{len(docs)} processed", end="", flush=True)
        if not busy:
            break
        time.sleep(2)
    print()
    for d in sorted(docs, key=lambda d: d["filename"]):
        print(f"  {d['filename']:<28} {d['status']:<13} {d['invoice_count']:>3} record(s) {d['error_code'] or ''}")


if __name__ == "__main__":
    main()
