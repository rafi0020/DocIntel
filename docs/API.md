# REST API

Interactive OpenAPI docs: **http://localhost:8000/docs** (Swagger UI) and `/openapi.json`.

## Authentication and roles

Every `/api` route except `/api/health`, `/api/auth/config`, `/api/auth/login` and `/api/auth/signup`
requires a signed-in user. Three ways to authenticate:

| Client | How |
|---|---|
| The web UI | `POST /api/auth/login` sets an **HttpOnly, SameSite=Lax session cookie**. Image and download links work because the browser sends the cookie. |
| Scripts | `POST /api/auth/login` returns a `token`; send `Authorization: Bearer <token>`. |
| Service account | Set `API_KEY` in `.env` and send `X-API-Key: <key>`. It has **reviewer** rights and cannot manage users. |

| Role | Can do |
|---|---|
| `viewer` | Read everything: documents, records, search, analytics, exports. |
| `reviewer` | Everything a viewer can, plus upload, correct, approve, resolve issues, re-process, cross-verify, bulk actions, and delete **their own** uploads. |
| `admin` | Everything, plus delete any document, manage users and read the audit log. |

A `401` means not signed in (or the session expired); a `403` means signed in without the needed role.
Sessions are server-side and revocable; five wrong passwords lock an account for ten minutes; state-changing
requests that carry the cookie must come from an allowed `Origin`. Demo accounts are in the README.

```bash
TOKEN=$(curl -s localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"reviewer@docintel.demo","password":"Reviewer#Demo2026"}' | jq -r .token)
curl -H "Authorization: Bearer $TOKEN" localhost:8000/api/documents
```

## Endpoints

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/documents` | Upload 1–50 files (`multipart/form-data`, field `files`). Returns `202` with the queued documents and any rejected files with a reason. |
| `GET` | `/api/documents` | List documents. Query: `status` (comma-separated), `q` (filename), `limit`, `offset`. |
| `GET` | `/api/documents/status?ids=a,b,c` | Batch status polling (status, stage, progress, error). |
| `GET` | `/api/documents/{id}` | Detail: pages (method, OCR confidence), extracted records (summary), processing history. |
| `GET` | `/api/documents/{id}/status` | Status of one document. |
| `GET` | `/api/documents/{id}/results` | **Structured results**: every record with fields (value, confidence, location, method), line items, validation issues and corrections. `409` while still processing. |
| `GET` | `/api/documents/{id}/pages/{n}` | Page text and word boxes, or sheet rows. |
| `GET` | `/api/documents/{id}/pages/{n}/image` | Rendered page PNG (cached). |
| `GET` | `/api/documents/{id}/file` | Download the original. |
| `POST` | `/api/documents/{id}/reprocess` | Re-run a **failed** job (`?force=true` for any finished document). |
| `POST` | `/api/documents/reprocess-failed` | Re-queue every failed document. |
| `DELETE` | `/api/documents/{id}` | Delete a document, its results and files. |
| `GET` | `/api/invoices/{id}` | One record with provenance, issues and correction history. |
| `PATCH` | `/api/invoices/{id}` | **Manual correction** of fields and/or line items. Values are parsed and checked (`422` on bad input), the change is audited (old → new, the signed-in user, note; a `reviewer` name in the body is ignored) and the record is re-validated, including duplicate and ledger cross-checks. |
| `POST` | `/api/invoices/{id}/approve` | Reviewer approves a record (clears the review flag, audited). |
| `POST` | `/api/invoices/{id}/issues/{issue_id}/resolve` | Mark one issue resolved. |
| `GET` | `/api/search` | Search records. `q`, `mode` = `hybrid` (default) \| `keyword` \| `semantic`; filters `review_status`, `needs_review`, `supplier`, `customer`, `date_from`, `date_to`, `min_total`, `max_total`, `currency`, `issue_code`, `file_type`, `record_kind`, `document_id`; `limit`, `offset`. Without `q` it lists records newest first with the filters applied. |
| `POST` | `/api/compare` | **Cross-verification.** Body: `{"left_document_ids": [...], "right_document_id": "..."}` (or `left_document_id`). Matches invoices across the documents and returns field and line-item differences with hints. |
| `GET` | `/api/compare` | Recent comparisons. |
| `GET` | `/api/stats` | Dashboard numbers: documents by status, records by review state, top issues, timings by source type. |
| `POST` | `/api/documents/bulk` | `{"ids": [...], "action": "reprocess" \| "delete"}`. Reports `done` and `skipped` with a reason for each (for example "not the uploader"). Reviewer. |
| `POST` | `/api/invoices/bulk-approve` | `{"ids": [...]}`: approves records that have no open errors; the rest are reported as skipped. Reviewer. |
| `GET` | `/api/analytics` | Dashboard data: daily volumes, review outcomes, spend by supplier and currency, open issues, speed, team activity. Query `days` (7 to 365). |
| `GET` | `/api/export` | Download records as `csv`, `xlsx` or `json` (`?format=`), accepting the same filters as search. Text that starts with `=`, `+`, `-` or `@` is neutralised so a malicious invoice cannot inject spreadsheet formulas. |
| `GET` | `/api/activity` | Recent team activity (uploads, approvals, corrections). Any signed-in user; no IP addresses. |
| `GET` | `/api/health` | Database, queue (workers, queued jobs) and extraction configuration. **Public.** |

### Model settings and system status

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/settings/models` | **Admin.** Current model and API settings. The key is **never returned**: only `key_set` and a masked `key_hint` (last four characters). `source` says whether the values come from the app (`ui`) or the `.env` defaults (`env`). |
| `PUT` | `/api/settings/models` | **Admin.** Save provider, model, base URL, key, on/off switch, tuning and OCR engine. Omit `api_key` to keep the saved key, send `clear_key: true` to remove it. Takes effect for the next document, no restart. Audited without the key. |
| `POST` | `/api/settings/models/test` | **Admin.** Send one tiny request using the supplied values (and the saved key if none is typed) and report success, latency or the error. Saves nothing; the key is redacted from any error text. |
| `DELETE` | `/api/settings/models` | **Admin.** Discard the saved settings and fall back to the `.env` defaults. |
| `GET` | `/api/settings/models/active` | Any signed-in user. Which model is in use (name only). |
| `GET` | `/api/system/status` | Any signed-in user. Database, queue and workers, active extractor, the last 24 hours (processed, failed, average and p95 time) and recent failures. |
| `POST` | `/api/system/ping-model` | Reviewer. Live check of the active model, cached for 8 seconds. |

### Accounts

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/auth/config` | Public. Only whether sign-up is open; it never reveals accounts or passwords. |
| `POST` | `/api/auth/signup` | Create an account (role `reviewer`) and sign in. Password: at least 10 characters with a letter and a number. `403` when `ALLOW_SIGNUP=false`. |
| `POST` | `/api/auth/login` | `{"email", "password", "remember"}` returns `{user, token}` and sets the cookie. Generic error for unknown e-mail or wrong password; `429` while locked. |
| `POST` | `/api/auth/logout` | Revokes the session. |
| `GET` / `PATCH` | `/api/auth/me` | The signed-in user; change your display name. |
| `POST` | `/api/auth/me/password` | Change your password; your other sessions are signed out. |
| `GET` / `POST` | `/api/users` | Admin. List users; create one. |
| `PATCH` | `/api/users/{id}` | Admin. Change name, role, active state, or set a new password (signs the user out). The last active administrator cannot be demoted or deactivated. |
| `GET` | `/api/audit` | Admin. Filter by `action` prefix (`auth`, `document`, `invoice`, `user`, `compare`, `export`), `user` e-mail, `days`; paged. |

## Examples

```bash
# upload several files
curl -F files=@samples/inv_000.pdf -F files=@samples/inv_008.png -F files=@samples/ledger_ap_2026.xlsx \
     http://localhost:8000/api/documents

# poll
curl "http://localhost:8000/api/documents/status?ids=<id1>,<id2>"

# results
curl http://localhost:8000/api/documents/<id>/results

# correct a field
curl -X PATCH http://localhost:8000/api/invoices/<record-id> \
     -H 'Content-Type: application/json' \
     -d '{"fields": {"invoice_number": "HC/694040", "total": "5,374.79"}, "reviewer": "rafi", "note": "read from the paper copy"}'

# search: meaning-based, filtered
curl "http://localhost:8000/api/search?q=mobility%20equipment%20hire&mode=semantic&min_total=100"

# all invoices received vs the ledger
curl -X POST http://localhost:8000/api/compare -H 'Content-Type: application/json' \
     -d '{"left_document_ids": ["<pdf-1>", "<pdf-2>"], "right_document_id": "<ledger-xlsx>"}'
```

## Result shape (one record)

```json
{
  "invoice_number": "HC/694040",
  "invoice_date": "2026-06-09",
  "supplier_name": "Evergreen Medical Equipment Inc.",
  "customer_name": "Maple Grove Assisted Living",
  "subtotal": 5118.85, "tax": 255.94, "total": 5374.79, "currency": "BDT",
  "line_items": [{"description": "Home health aide hours", "quantity": 12, "unit_price": 29.17, "amount": 350.04}],
  "fields": {
    "total": {"value": 5374.79, "confidence": 0.95, "method": "llm+rules",
              "source": {"page": 1, "box": [0.81, 0.62, 0.90, 0.64]}, "note": null, "candidate": null},
    "invoice_number": {"value": null, "confidence": 0.0, "candidate": "HC-694O40",
                       "note": "Proposed value could not be found in the document text, so it was not used."}
  },
  "issues": [{"code": "line_item_arithmetic", "severity": "warning", "field": "line_items",
              "message": "Line 6: 1 × 234.36 = 234.36, but amount is 234.00."}],
  "needs_review": true, "review_status": "needs_review"
}
```

`source` is a page number with a normalised box (0–1) for documents, or `{"sheet", "row", "col"}`
for spreadsheet cells.

## Validation issue codes

| Code | Severity | Meaning |
|---|---|---|
| `missing_field` | error / warning | Required (number, date, supplier, total) / expected (customer, subtotal, tax, currency) field not found |
| `invalid_number`, `invalid_date` | error | A spreadsheet cell does not hold a valid value |
| `unverified_value` | warning | An extractor proposed a value that is not in the document; it was not used |
| `total_mismatch` | error | Subtotal + tax ≠ total (exact to the cent) |
| `line_items_mismatch` | error | Σ line items ≠ subtotal |
| `line_item_arithmetic` | warning | qty × unit price ≠ amount |
| `tax_exceeds_subtotal`, `unusual_tax_rate`, `negative_amount`, `non_positive_total` | error / warning | Numeric sanity |
| `future_date`, `implausible_date`, `ambiguous_date` | warning | Date checks (03/04 read per `AMBIGUOUS_DATE_ORDER`) |
| `low_confidence`, `extractor_disagreement` | warning | Confidence below threshold, or rules and LLM read different values |
| `duplicate_invoice` | error | Same invoice number (and supplier) already received |
| `duplicate_file` | warning | Identical file uploaded before |
| `possible_duplicate` | warning | Same supplier, date and total under a different number |
| `ledger_mismatch` / `ledger_match` | error / info | Document vs ledger row with the same number |
| `llm_fallback` | info | LLM unavailable; rule-based result used |
