# Sample documents

A small, self-contained demo set generated with `backend/eval/generate_dataset.py --seed 99`, plus two invoices from
the public labelled set used in the evaluation. Ground truth for every generated file is in `ground_truth.json`.

| File | What it shows |
|---|---|
| `inv_000.pdf` … `inv_011.*` | Home-care invoices: digital PDFs, JPG/PNG/TIFF scans of varying quality, 4 layouts |
| `inv_003.jpg` | Printed total ≠ subtotal + tax (`total_mismatch`) |
| `inv_006.pdf` | One line amount wrong (`line_items_mismatch`, `line_item_arithmetic`) |
| `inv_008.png` | Poor-quality scan (rotated, blurred, washed out) |
| `dup_0_inv_000.pdf`, `dup_1_inv_006.pdf` | The same invoices sent again (`duplicate_invoice`) |
| `batch_multi_invoice.pdf` | 25 invoices in one PDF split into 25 records |
| `ledger_ap_2026.xlsx` | Accounts-payable ledger (3 sheets) for the same invoices; three rows were entered incorrectly (two dates, one total) and are detected by cross-verification |
| `ledger_ap_2026.csv`, `ledger_q1.xls` | The same ledger as CSV and legacy XLS |
| `real_invoice_a.png`, `real_invoice_b.png` | Real-layout invoices from the public Sparrow set (MIT) |
| `corrupt_random.pdf`, `corrupt_empty.png`, `damaged_truncated.pdf` | Broken files that produce specific failure codes or partial recovery |

Load them all into a running stack with `python scripts/seed_demo.py`.
