"""Convert the public, third-party labelled invoice set into our manifest format.

Source: katanaml-org/invoices-donut-data-v1 on Hugging Face (MIT licence),
"Sparrow" invoice images with human-curated JSON labels. Neither the images nor
the labels were produced by this project, which keeps this part of the
evaluation independent of our own generator.

Mapping of their labels to our schema:
  header.invoice_no            -> invoice_number
  header.invoice_date          -> invoice_date (MM/DD/YYYY in this set)
  header.seller / header.client-> supplier_name / customer_name
                                  (their label is name + address in one string; a
                                  prediction is scored correct when it equals the
                                  leading name part, see run_eval.name_match)
  summary.total_net_worth      -> subtotal
  summary.total_vat            -> tax
  summary.total_gross_worth    -> total
  "$" in amounts               -> currency USD
  items[].item_desc/qty/net_price/net_worth -> line items

Usage: python -m eval.prepare_real --parquet test.parquet --out ../dataset/real_test
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path


def convert(parquet: Path, out: Path) -> int:
    import pandas as pd
    from PIL import Image

    from app.extraction.normalize import parse_amount, parse_date

    df = pd.read_parquet(parquet)
    (out / "files").mkdir(parents=True, exist_ok=True)
    files = []
    for i, row in df.iterrows():
        gt = json.loads(row["ground_truth"])["gt_parse"]
        if set(gt) == {"None"}:  # one label is wrapped in a stray "None" key
            gt = gt["None"]
        flat = "header" not in gt  # a few labels use a flat schema with a single item
        h, s = gt.get("header", gt), gt.get("summary", gt)
        name = f"real_{i:03d}.png"
        Image.open(io.BytesIO(row["image"]["bytes"])).convert("RGB").save(out / "files" / name)

        def amt(v):
            a = parse_amount(v)
            return float(a) if a is not None else None

        d, _ = parse_date(h.get("invoice_date"), "MDY")
        items = gt.get("items") or []
        if isinstance(items, dict):
            items = [items]
        has_dollar = any("$" in str(v) for v in s.values())
        files.append({
            "file": name, "kind": "invoice", "format": "png", "quality": "real", "expected": "ok", "planted_issues": [],
            "label_source": "katanaml-org/invoices-donut-data-v1",
            "invoices": [{
                "invoice_number": h.get("invoice_no"),
                "invoice_date": d.isoformat() if d else None,
                "supplier_name": h.get("seller"),
                "customer_name": h.get("client"),
                "subtotal": amt(s.get("total_net_worth")),
                "tax": amt(s.get("total_vat")),
                "total": amt(s.get("total_gross_worth")),
                "currency": "USD" if has_dollar else None,
                # flat labels only describe one item, so their item list is not scored
                "line_items": None if flat else [
                    {"description": it.get("item_desc"), "quantity": amt(it.get("item_qty")),
                     "unit_price": amt(it.get("item_net_price")), "amount": amt(it.get("item_net_worth"))}
                    for it in items
                ],
            }],
            "name_fields_include_address": True,
        })
    (out / "manifest.json").write_text(json.dumps({"source": str(parquet.name), "files": files}, indent=1))
    return len(files)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    print(f"wrote {convert(Path(a.parquet), Path(a.out))} documents")
