# Evaluation report

All figures are measured and were produced by `backend/eval/run_eval.py` and
`backend/eval/scale_test.py` running the same `process_document()` function the
background worker runs. Raw outputs (per-file results, predictions, summaries) are in
[`eval_results/`](../eval_results).

> **Configurations measured:** sections 1 to 7 use the rule-based extractor + Tesseract OCR
> (`LLM_PROVIDER=rules`), which is what runs with no API key. Section 8 repeats the evaluation with a live LLM
> added (hybrid extraction) so the two can be compared side by side.

## 1. Datasets

| Split | Source | Labels | Files | Used for |
|---|---|---|---|---|
| `synthetic_dev` | Generator, seed 1 | Exact (generated with the document) | 53 | Development and tuning |
| `synthetic_test` | Generator, seed 2 | Exact | 73 | **Reported results** |
| `real_dev` | `katanaml-org/invoices-donut-data-v1` validation split (MIT) | Third-party, human-curated | 50 | Development |
| `real_test` | same dataset, test split | Third-party | 26 | **Reported results** |

**Synthetic set (`eval/generate_dataset.py`).** Home-care billing documents: agencies, staffing
and equipment suppliers, visit-hours × rate line items, 1–22 items, BDT/USD/EUR/GBP with symbols
or codes, US and European number formats, 5 date formats, **4 layouts** with different labels
("Invoice No / Invoice # / Bill No / Invoice Number", "Total Due / Amount Due / Grand Total / Balance
Due", distractor dates such as due dates and service periods), multi-page invoices with
"Page x of y". Formats: digital PDF, scanned PDF, JPG, PNG, multi-frame TIFF, at three scan
qualities (clean; medium = ±1.2° rotation, blur, noise, JPEG q70; poor = ±2.5° rotation, heavier
blur and noise, 0.6× downscale, washed-out contrast, JPEG q35). Each split also has: a
multi-invoice batch PDF, an XLSX ledger (3 sheets), the same ledger as CSV and XLS, two re-sent
duplicates, 6 corrupted files and one truncated PDF. Planted errors: printed total ≠ subtotal + tax,
a wrong line amount, a missing invoice number, a missing tax line; and 11–12 ledger rows entered
wrongly (transposed totals, dates off by a day).

**Real set.** Rendered invoice images with labels curated by a third party. They are independent of
this project's generator and labelling, which avoids grading our own homework, but they come from a
single template family with clean scans, so they are an easier test than real-world variety.
Supplier/customer labels include the address in one string; a prediction is scored correct when it
equals the leading name part. Two labels in the dev split use a flat schema with one item; their
line items are excluded from item scoring.

**Caveats**
- The generator and the rule extractor were written by the same authors, so the synthetic numbers
  measure robustness to scan quality and layout variation within known label vocabularies, not
  generalisation to unseen invoice designs. The real set is the better check of that.
- Tuning was done on the dev splits only. One change was made after looking at test-split results:
  the arithmetic tolerance was relative (0.5%), which let an $81 error on a $181k invoice pass. That
  was a logic error (invoice arithmetic is exact to the cent), not a threshold tweak. It was fixed and
  all splits were re-run. Validation recall on the test split was 83.3% before the fix and 96.7% after.
- Machines: the rule-based measurements ran in a cloud sandbox with 2 vCPU and 7 GB RAM; the hybrid (LLM)
  measurements ran in a local Docker container. Timings depend on the hardware.

## 2. Metrics

| Metric | Definition |
|---|---|
| Field accuracy | Per field (8 fields) per invoice: amounts within ±0.01; dates equal; invoice numbers equal after removing punctuation/case; names equal or ≥ 90 token-sort similarity; currency equal. **Null vs null counts as correct**; a value where the truth is null counts as a **hallucination**. |
| Line items | A predicted item matches a true item when the amounts are equal (±0.01) and descriptions are similar (token-set ≥ 70). Precision, recall, F1. |
| Validation | Recall on planted errors (the issue code must be raised); false-alarm rate = clean documents sent to review. |
| Cross-verification | Of the ledger rows deliberately entered wrongly, how many were reported as a field mismatch; false flags = mismatches reported on rows that were not altered. |
| Success / failure rate | Valid files processed without error / valid files that failed. Bad files: rejected with the expected error code. |
| Speed | Wall time per file and per page through `process_document()` (OCR, extraction, validation; DB writes and embeddings excluded, see §6). |

## 3. Results: held-out test splits

| | Synthetic test | Real test |
|---|---|---|
| Files | 73 (66 valid + 7 bad/damaged) | 26 |
| **Document success rate** | **100%** (66/66) | **100%** (26/26) |
| **Failure rate** | **0%** | **0%** |
| Bad files rejected with the correct error code | 6/6 | – |
| Crashes | 0 | 0 |
| **Field accuracy (overall)** | **99.0%** | **99.0%** |
| Hallucinated values | **0** | **0** |
| Line items P / R / **F1** | 99.0 / 98.6 / **98.8%** | 98.0 / 94.3 / **96.2%** |
| Validation recall on planted errors | 96.7% (29/30) | – |
| Clean docs sent to review (false alarms) | 10.5% (4/38) | 3.8% (1/26) |
| Multi-invoice PDF split | 40/40 invoices, 42 pages | – |
| Ledger rows wrongly entered and caught | 11/11 (2 false flags) | – |

### Per field

| Field | Synthetic test | Real test |
|---|---|---|
| invoice_number | 99.0 | 100.0 |
| invoice_date | 99.0 | 100.0 |
| supplier_name | 100.0 | 96.2 |
| customer_name | 100.0 | 100.0 |
| subtotal | 98.0 | 100.0 |
| tax | 98.0 | 100.0 |
| total | 99.0 | 96.2 |
| currency | 99.0 | 100.0 |

### By scan quality (synthetic test, field accuracy)

| Clean | Medium | Poor | Batch PDF |
|---|---|---|---|
| 99.7% | 100.0% | 89.1% | 100.0% |

### Validation recall by planted error (synthetic test)

| Error | Caught |
|---|---|
| Missing field | 11/11 |
| Total ≠ subtotal + tax | 9/9 |
| Line items ≠ subtotal | 5/5 |
| qty × price ≠ amount | 4/5 (the miss: OCR lost the affected row on a poor scan) |

### Dev splits (for reference)

| | Synthetic dev | Real dev |
|---|---|---|
| Field accuracy | 99.0% | 99.8% |
| Line-item F1 | 99.3% | 96.4% |
| Validation recall | 100% (16/16) | – |
| False-alarm rate | 21.4% | 8.0% |

## 4. Scale: a 1,000-page PDF

`eval/scale_test.py` builds a 1,000-page PDF of 969 invoices (1–3 pages each, 4 layouts) and a
100-page scanned (image-only) batch, and runs both through the pipeline.

| | 1,000-page digital PDF | 100-page scanned PDF |
|---|---|---|
| File size | 1.2 MB | 13.1 MB |
| **Total time** | **3.9 s** (254 pages/s) | 53.1 s (**0.53 s/page**, 2 OCR threads) |
| Invoices found / expected | **969 / 969** | 98 / 99 |
| Invoices matched by number | 969 | 97 |
| Field accuracy | 100.0% | 96.5% |
| Peak memory (process) | 1.5 GB (both runs, incl. OCR models) | |

For a 1,000-page **scanned** PDF, extrapolating linearly: about 9 minutes on 2 cores. OCR is
per-page parallel (`OCR_THREADS`), and documents are parallel across workers.

## 5. OCR engine comparison (synthetic test, same extractor)

| | Tesseract (default) | RapidOCR (PP-OCR) |
|---|---|---|
| Field accuracy | **99.0%** | 86.9% |
| Clean / medium / poor scans | 99.7 / **100.0** / **89.1%** | 98.1 / 50.0 / 35.9% |
| Line-item F1 | **98.8%** | 89.8% |
| Time per page, image / scanned PDF (p50) | **0.61 / 0.74 s** | 1.98 / 2.97 s |

RapidOCR's default recognition model drops the spaces between English words, which breaks label
matching. Tesseract became the default after this comparison.

## 6. Speed (synthetic test, per file, p50 / p95)

| Type | p50 | p95 |
|---|---|---|
| Digital PDF | 5.6 ms | 14.2 ms |
| Image (OCR) | 613 ms | 845 ms |
| Scanned PDF (OCR) | 900 ms | 1,272 ms |
| Spreadsheet | 8.6 ms | 87.8 ms |
| 40-invoice batch PDF (42 pages) | 230 ms | |

Real test images (2481×3508 px, larger than the synthetic scans): p50 1.66 s per file.

Beyond the pipeline, the worker also writes to PostgreSQL, computes embeddings (about 0.1 s per
record on this 2-vCPU sandbox, which dominates for large digital batches) and runs cross-record
checks. These are recorded per document in `processing_events` and shown in the UI's History tab.

## 7. Failure analysis

Every miss on the test splits, read from `eval_results/rules/*/predictions.json`:

**Real test**
- `real_013.png`, total: OCR dropped one digit (read 157,929.37 for 1,579,929.37). One line item
  in the same file has a stray "2," at the start of its description, so it didn't match.
- `real_022.png`, supplier: the dataset label is incorrect (`907-77-8965`, a tax ID). The system read the
  company name, "George, Casey and Harris". It is counted as a miss.
- `real_025.png`, line items: the item table was not recognised (0 of 5 items) because the table
  header and the tax-ID line were read as one line. The validator flagged the record
  (`line_items_mismatch`), so it went to review instead of passing. That flag is also the one
  "false alarm" on the real set.

**Synthetic test**
- Field misses (4 values in total) are all on poor-quality scans where OCR misread or lost text.
- `inv_032.jpg` (poor scan): one of two item rows was lost by OCR, so the planted
  qty × price error could not be checked. The record was still sent to review by the other
  planted error.
- False alarms (4/38): all are OCR digit misreads in line items (`inv_051.jpg`, a clean JPG, and
  three medium/poor scans) caught by `line_item_arithmetic`. The arithmetic check flags these
  correctly: the values as read are inconsistent and need review.
- Cross-verification false flags (2): both caused by an OCR misread on the document side. They are
  real differences between what was read and the ledger.

## 8. LLM extraction (live run)

The hybrid extractor runs the rule engine **and** an LLM on every invoice; both answers go through the same
provenance check (a value is kept only if it can be located in the document), and agreement raises confidence
while disagreement flags the field for review. It is implemented for Anthropic, Gemini, Groq, OpenAI, Ollama and any
OpenAI-compatible gateway, and covered by tests with mocked providers.

It was also **measured live** on both held-out test splits: `claude-haiku-4-5` reached through an
OpenAI-compatible gateway, temperature 0, same code path as the workers, same files as sections 3 to 7
(the datasets regenerate byte-identically from the documented seed and the public parquet).
Raw outputs: [`eval_results/hybrid_llm/`](../eval_results/hybrid_llm).

| | Synthetic test: rules | Synthetic test: **rules + LLM** | Real test: rules | Real test: **rules + LLM** |
|---|---|---|---|---|
| Document success / failure rate | 100% / 0% | 100% / 0% | 100% / 0% | 100% / 0% |
| Field accuracy (overall) | 99.0% | 99.0% | 99.0% | 99.0% |
| Hallucinated values | 0 | 0 | 0 | 0 |
| Provenance rejections (LLM values not on the page) | – | 0 | – | 0 |
| Line items F1 | 98.8% | 98.8% | 96.2% | **99.1%** |
| Validation recall on planted errors | 96.7% (29/30) | **100% (30/30)** | – | – |
| Clean documents sent to review | 10.5% (4/38) | 18.4% (7/38) | 3.8% (1/26) | 38.5% (10/26) |
| Ledger rows wrongly entered and caught | 11/11 | 11/11 | – | – |
| Median time per file | 10 ms | 2.9 s | 1.7 s | 5.8 s |
| p95 time per file | 0.96 s | 5.8 s | 1.8 s | 7.6 s |
| Wall time for the split (sequential) | 21.5 s | 226 s | 41.8 s | 153 s |

Observations:

- **Field accuracy did not improve.** The rule engine is already at 99.0% on these sets, so the LLM has little headroom.
  Both pipelines miss the same fields on the real set (one supplier name and one total, 96.2% each).
- **Where the LLM helps:** line items on real, differently laid-out invoices (F1 96.2% to 99.1%, mostly recall) and
  planted-error recall on the synthetic set (the one error rules missed is now caught).
- **What it costs:** every file takes 2.9 to 5.8 s instead of milliseconds to 2 s, and far more clean documents are
  routed to a human (38.5% of real invoices, up from 3.8%), because any rule/LLM disagreement on a field is flagged.
  That is the intended safety behaviour, but it means the LLM raises review workload on this data.
- **Safety held:** 0 invented values and 0 provenance rejections, so the model never proposed a value that was
  not on the page in these runs.
- The sets are small (73 and 26 files), so differences of one or two documents are within noise.

Recommendation: keep the rule engine as the default (fast, free, private) and enable the LLM where layouts vary, or
only for low-confidence records.

To repeat it with any provider:

```bash
cd backend
LLM_PROVIDER=anthropic LLM_API_KEY=... LLM_MODEL=claude-haiku-4-5 \
  python -m eval.run_eval --manifest ../dataset/real_test/manifest.json --out ../eval_results/hybrid_llm/real_test
```

## Reproduce

```bash
cd backend
python -m eval.generate_dataset --out ../dataset/synthetic_test --seed 2 --n 60 --batch 40
python -m eval.prepare_real --parquet test.parquet --out ../dataset/real_test   # parquet from Hugging Face
python -m eval.run_eval --manifest ../dataset/synthetic_test/manifest.json --out ../eval_results/rules/synthetic_test
python -m eval.scale_test --pages 1000 --scan-pages 100 --out ../eval_results/rules/scale
```
