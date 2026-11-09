# Database schema

PostgreSQL 16 with the `vector` (pgvector) and `pg_trgm` extensions. Tables are created by
`app/db.py:init_db()` from the SQLAlchemy models in `app/models.py`.

```mermaid
erDiagram
    documents ||--o{ pages : "has"
    documents ||--o{ invoices : "yields"
    documents ||--o{ processing_events : "history"
    invoices ||--o{ validation_issues : "flags"
    invoices ||--o{ corrections : "audit trail"
    documents ||--o{ reconciliations : "left / right"
    users ||--o{ documents : "uploads"
    users ||--o{ auth_sessions : "signed in"
    users ||--o{ audit_log : "actions"

    documents {
        uuid id PK
        varchar filename
        varchar file_type "pdf png jpg tiff xlsx xls csv"
        bigint size_bytes
        varchar sha256 "duplicate-file detection"
        uuid uploaded_by_id FK "who uploaded it"
        varchar storage_path
        varchar status "queued processing completed needs_review failed"
        varchar stage
        float progress
        varchar source_kind "digital_pdf scanned_pdf mixed_pdf image spreadsheet"
        int page_count
        int invoice_count
        varchar error_code
        text error_message
        int attempts
        int processing_ms
        varchar extractor
        text full_text
        timestamptz created_at
        timestamptz finished_at
    }
    pages {
        int id PK
        uuid document_id FK
        int page_no "sheet index for spreadsheets"
        varchar label "sheet name"
        varchar method "text ocr table"
        float ocr_confidence
        text text
        jsonb layout "word boxes, or sheet rows"
        text error
    }
    invoices {
        uuid id PK
        uuid document_id FK
        int position
        varchar record_kind "document or ledger_row"
        int page_start
        int page_end
        varchar sheet_name
        int row_index
        varchar invoice_number
        varchar invoice_number_norm
        date invoice_date
        varchar supplier_name
        varchar supplier_norm
        varchar customer_name
        numeric subtotal
        numeric tax
        numeric total
        varchar currency
        jsonb fields "value, confidence, source box, method, note per field"
        jsonb line_items
        float confidence
        varchar review_status "auto_approved needs_review corrected approved"
        bool needs_review
        text search_text
        tsvector search_tsv "generated, GIN index"
        vector embedding "384-d, pgvector"
    }
    validation_issues {
        int id PK
        uuid invoice_id FK
        varchar code
        varchar severity "error warning info"
        varchar field
        text message
        jsonb details
        bool resolved
    }
    corrections {
        int id PK
        uuid invoice_id FK
        varchar field
        jsonb old_value
        jsonb new_value
        varchar corrected_by
        text note
        timestamptz created_at
    }
    processing_events {
        int id PK
        uuid document_id FK
        int attempt
        varchar stage "ingest extract validate index cross_checks processing"
        varchar status "started ok warning error"
        text message
        int duration_ms
    }
    users {
        uuid id PK
        varchar email UK "stored lower-case"
        varchar name
        varchar password_hash "scrypt, salted"
        varchar role "admin reviewer viewer"
        bool is_active
        int failed_attempts
        timestamptz locked_until
        timestamptz last_login_at
    }
    auth_sessions {
        uuid id PK
        uuid user_id FK
        varchar token_hash UK "SHA-256 of the cookie token"
        varchar user_agent
        varchar ip
        timestamptz last_seen_at
        timestamptz expires_at
    }
    audit_log {
        bigint id PK
        uuid user_id FK "nullable, kept as e-mail if the user is removed"
        varchar user_email
        varchar action "auth.login document.upload invoice.approve user.update ..."
        varchar target_type
        varchar target_id
        jsonb detail
        varchar ip
        timestamptz created_at
    }
    app_settings {
        varchar key PK "models"
        jsonb value "provider, model, base_url, tuning, api_key_enc (encrypted)"
        varchar updated_by
        timestamptz updated_at
    }
    reconciliations {
        uuid id PK
        uuid left_document_id FK
        uuid right_document_id FK
        jsonb summary
        jsonb result
    }
```

## Why it is shaped this way

- **`documents` vs `invoices`.** One upload can hold many invoices (a 1,000-page batch, a ledger with hundreds of rows), so extracted records are their own table. `record_kind` separates invoice documents from ledger rows: duplicates are checked within a kind, and the two kinds are cross-checked against each other.
- **Typed columns and a JSON `fields` column.** Number, date, parties and amounts are real columns (indexed, filterable, sortable, `numeric(18,2)` for money). The full per-field result (confidence, bounding box or cell address, which extractor, notes, rejected candidates) lives in `fields` so the UI can explain every value without schema churn.
- **Normalised keys.** `invoice_number_norm` (alphanumerics, upper case) and `supplier_norm` (no punctuation or company suffixes) drive duplicate detection and cross-checks.
- **Search columns.** `search_tsv` is a *generated* column, so it can never drift from `search_text`; it has a GIN index. A trigram index on `supplier_name` serves partial name matches. `embedding` is a pgvector column for semantic search.
- **Audit trail.** Corrections are append-only with old and new values, the reviewer and an optional note; approvals are recorded there too. `processing_events` keeps per-attempt, per-stage timings and errors, which is what the History tab and the evaluation's timing figures come from.

- **Accounts.** `users`, `auth_sessions` and `audit_log` are separate from the document tables. Only a hash of the session token is stored, so a database leak does not hand out live sessions. `audit_log` keeps the e-mail and name next to the (nullable) user id so history survives a user being removed. `app_settings` holds runtime configuration edited from the UI; the API key inside it is stored encrypted, never in plain text. Existing databases gain `documents.uploaded_by_id` automatically at start-up.

## Indexes

| Index | Purpose |
|---|---|
| `documents(status)`, `documents(sha256)` | Inbox filters, duplicate-file check |
| `invoices(document_id)`, `(invoice_number)`, `(invoice_number_norm)`, `(supplier_norm)`, `(invoice_date)`, `(total)`, `(review_status)`, `(needs_review)` | Filters, duplicate and ledger cross-checks |
| `invoices USING gin(search_tsv)` | Keyword search |
| `invoices USING gin(supplier_name gin_trgm_ops)` | Partial supplier matching |
| `validation_issues(invoice_id)`, `(code)` | Review queue, "has issue" filter |
| `users(email)` unique, `auth_sessions(token_hash)` unique, `auth_sessions(expires_at)`, `audit_log(created_at)`, `(action)`, `(user_id)`, `documents(uploaded_by_id)` | Sign-in, session lookup and clean-up, audit filters |
| `pages(document_id)`, `corrections(invoice_id)`, `processing_events(document_id)` | Detail views |

At larger scale, add an HNSW index on `invoices.embedding` (`vector_cosine_ops`) for approximate nearest-neighbour search.
