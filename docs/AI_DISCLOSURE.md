# AI assistance disclosure

DocIntel was developed with AI coding assistance. This document states what was generated, what was decided by the
maintainer, and how the result was verified.

## Tools

| Tool | Use |
|---|---|
| Claude (Anthropic), via Claude Code | Code generation, refactoring, tests, evaluation scripts, documentation, debugging, running the Docker stack and the evaluations |
| Playwright | Scripted browser checks of the UI across viewports and themes; README screenshots |
| Archify | Generation and validation of the architecture diagram in `docs/architecture.html` |
| An LLM (optional, runtime) | Invoice field extraction when a model is configured; see [PROMPTS.md](PROMPTS.md) |

## Division of responsibility

The maintainer defined the requirements, made the architecture and scope decisions, reviewed every change and the
measured results, and approved what was merged. The assistant implemented under that direction. Decisions taken
with the maintainer include:

- A single Python service for the API and workers, Redis with RQ for the queue, and PostgreSQL with pgvector for
  records, full-text search and embeddings.
- Evaluation on a synthetic home-care dataset plus an independent public dataset, reported per split.
- Cross-verification of invoices against ledgers, click-to-source highlighting and large-PDF splitting.
- Shared-workspace accounts with three roles, server-side sessions and an audit log.
- Encrypted storage of API keys entered in the UI, with saved settings overriding environment defaults.
- Rule-based extraction as the default, with the LLM optional.

## Verification

- 138 automated tests (`backend/tests`) covering every supported file type, corrupted inputs, OCR on degraded
  scans, extraction across layouts, provenance and hallucination rejection, mocked LLM providers, validation rules,
  reconciliation, every API endpoint, authentication, role enforcement, lock-out, CSRF origin checks, audit logging,
  bulk actions, export, and encrypted model settings. Results are in [`docs/test-results`](test-results).
- A measured evaluation on held-out data, including an independent real-world set. Defects found by the evaluation
  and by end-to-end runs were fixed with regression tests; examples include a relative tolerance that hid large
  arithmetic errors, line items lost on the second page of multi-page invoices, OCR decimal separators read as
  spaces, order-dependent matching in reconciliation, database connections shared across forked workers and a CORS
  configuration that blocked `PUT` requests from the browser.
- The full stack (PostgreSQL, Redis, API, workers, UI) was run under Docker Compose from empty volumes.
- The UI was audited with a scripted browser across 16 screens, light and dark themes and five viewport widths for
  overflow, unlabelled controls, console errors and failed requests.
- A scan of all tracked files for secrets.

## Data

No AI-generated data is presented as real. The synthetic dataset is produced by a deterministic generator in this
repository (`backend/eval/generate_dataset.py`). The real-invoice set is a public, third-party labelled dataset
(MIT) that is downloaded and converted by `backend/eval/prepare_real.py`.

## Runtime use of AI

LLM extraction is disabled until an administrator configures a provider. When enabled, document text is sent to the
configured provider; for sensitive documents use a local model (Ollama) or the rule engine. The prompt treats the
document as data, and every value the model returns must be located in the document before it is stored, so a model
cannot introduce values that are not on the page. The extraction prompt is reproduced in [PROMPTS.md](PROMPTS.md).

## Limitations

- The account system uses standard-library primitives (scrypt, SHA-256, HMAC) and the `cryptography` package
  rather than custom cryptography. It has been covered by automated tests and maintainer review, not an
  independent security audit.
- The LLM extraction path was measured on small evaluation sets (73 and 26 files); differences of one or two
  documents are within noise.
- Long invoices are clipped before being sent to a model, keeping the header pages and the final page where totals
  usually appear.
