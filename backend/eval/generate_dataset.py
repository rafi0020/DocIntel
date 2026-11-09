"""Generate a labelled synthetic dataset of home-care billing documents.

Output (in --out):
  files/                 the documents (digital PDFs, scanned PDFs, JPG/PNG/TIFF,
                         XLSX/XLS/CSV ledgers, corrupted files, a multi-invoice batch)
  manifest.json          ground truth for every file:
                           expected outcome (ok / fail), the invoices it contains,
                           planted validation errors, scan quality, and for ledgers
                           which rows were deliberately altered

Ground truth is produced by the same code that draws the document, so it is
exact. Documents vary in layout (4 templates), labels, date formats, currencies,
page count and scan quality; some contain planted errors (wrong totals, wrong
line items, missing invoice number, duplicates) to measure the validator.

Usage:  python -m eval.generate_dataset --out ../dataset/synthetic_test --seed 2 --n 60
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import cv2
import numpy as np

SUPPLIERS = [
    ("Sunrise Home Health Supplies", "412 Maple Ave, Columbus, OH 43215"),
    ("CarePoint Staffing Solutions LLC", "88 Harbor Blvd, Tampa, FL 33602"),
    ("Evergreen Medical Equipment Inc.", "1550 Pine St, Denver, CO 80202"),
    ("BrightPath Nursing Agency", "27 King Road, Newark, NJ 07102"),
    ("Dhaka Care Logistics Ltd.", "House 12, Road 5, Banani, Dhaka 1213"),
    ("Mohakhali Pharma Distributors", "51 Bir Uttam AK Khandakar Rd, Dhaka 1212"),
    ("Harmony Therapy Partners", "300 Lakeview Dr, Austin, TX 78701"),
    ("Lifeline Mobility Rentals", "9 Station Square, Leeds LS1 4DY"),
    ("Northstar Home Care Billing Co.", "71 Elm Court, Albany, NY 12207"),
    ("Greenleaf Nutrition Services", "640 Oak Lane, Portland, OR 97205"),
]
CUSTOMERS = [
    "Cottage Home Care Services", "Riverside Senior Living", "Maple Grove Assisted Living",
    "Golden Years Home Care Agency", "St. Anne Community Care", "Willow Creek Hospice",
    "Care Guide Operations", "Bayview Family Health", "Unity Home Health Network",
]
SERVICES = [
    ("Skilled nursing visit (RN)", (55, 95), "visit"),
    ("Home health aide hours", (18, 32), "hour"),
    ("Personal care assistance", (20, 35), "hour"),
    ("Physical therapy session", (80, 140), "session"),
    ("Occupational therapy session", (75, 130), "session"),
    ("Medication administration check", (25, 45), "visit"),
    ("Wound care supplies kit", (12, 48), "kit"),
    ("Incontinence supplies (case)", (30, 65), "case"),
    ("Wheelchair rental (monthly)", (60, 150), "month"),
    ("Hospital bed rental (monthly)", (110, 240), "month"),
    ("Overnight respite care", (140, 260), "night"),
    ("Caregiver training workshop", (150, 400), "session"),
    ("Blood pressure monitor", (35, 90), "unit"),
    ("Nutritional supplement pack", (15, 40), "pack"),
    ("Mileage reimbursement", (0.5, 0.7), "mile"),
]
CURRENCIES = [("USD", "$"), ("USD", "USD "), ("BDT", "BDT "), ("BDT", "Tk "), ("EUR", "EUR "), ("GBP", "GBP ")]
TAX_RATES = [Decimal("0"), Decimal("0.05"), Decimal("0.075"), Decimal("0.08"), Decimal("0.10"), Decimal("0.15")]

Q = Decimal("0.01")


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(Q, rounding=ROUND_HALF_UP)


def fmt_amount(v: Decimal, style: str) -> str:
    s = f"{v:,.2f}"
    if style == "eu":
        s = s.replace(",", "_").replace(".", ",").replace("_", ".")
    return s


DATE_FORMATS = [
    ("iso", lambda d: d.isoformat()),
    ("mdy", lambda d: d.strftime("%m/%d/%Y")),
    ("long", lambda d: d.strftime("%B %d, %Y").replace(" 0", " ")),
    ("dmon", lambda d: d.strftime("%d-%b-%Y")),
    ("dmy_long", lambda d: d.strftime("%d %B %Y").lstrip("0")),
]


def make_invoice(rng: random.Random, idx: int) -> dict:
    sup = rng.choice(SUPPLIERS)
    cust = rng.choice(CUSTOMERS)
    cur, sym = rng.choice(CURRENCIES)
    if cur == "BDT":
        scale = 110
    else:
        scale = 1
    n_items = rng.choices([1, 2, 3, 4, 5, 6, 8, 12, 22], weights=[6, 10, 12, 10, 8, 6, 4, 2, 2])[0]
    items = []
    for desc, (lo, hi), unit in rng.sample(SERVICES, k=min(n_items, len(SERVICES))) + [rng.choice(SERVICES) for _ in range(max(0, n_items - len(SERVICES)))]:
        if unit == "hour":
            qty = Decimal(rng.choice([2, 3, 4, 4.5, 6, 8, 10, 12, 16, 24, 40]))
        elif unit == "mile":
            qty = Decimal(rng.randint(20, 400))
        else:
            qty = Decimal(rng.randint(1, 12))
        price = money(rng.uniform(lo, hi) * scale)
        items.append({"description": desc, "quantity": float(qty), "unit_price": float(price), "amount": float(money(qty * price))})
    subtotal = money(sum(Decimal(str(i["amount"])) for i in items))
    rate = rng.choice(TAX_RATES)
    tax = money(subtotal * rate)
    total = subtotal + tax
    d = date(2026, 1, 1) + timedelta(days=rng.randint(0, 300))
    num_style = rng.choice(["INV-{y}-{n:04d}", "HC/{n:05d}", "{y}{n:05d}", "A-{n:04d}", "CG-{y}-{n:03d}"])
    number = num_style.format(y=d.year, n=1000 + idx * 7 + rng.randint(0, 6))
    return {
        "invoice_number": number,
        "invoice_date": d.isoformat(),
        "supplier_name": sup[0],
        "supplier_address": sup[1],
        "customer_name": cust,
        "subtotal": float(subtotal),
        "tax": float(tax),
        "tax_rate": float(rate),
        "total": float(total),
        "currency": cur,
        "symbol": sym,
        "line_items": items,
    }


# ----------------------------------------------------------------------- render
def render_pdf(inv: dict, template: int, date_fmt: str, num_style: str, hide_number: bool = False,
               printed: dict | None = None) -> bytes:
    """Draw the invoice. `printed` overrides values as printed (for planted errors)."""
    from reportlab.lib.pagesizes import A4, LETTER
    from reportlab.pdfgen import canvas

    pr = {**inv, **(printed or {})}
    size = LETTER if template in (0, 2) else A4
    W, H = size
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=size)
    sym = inv["symbol"]
    d = date.fromisoformat(inv["invoice_date"])
    dstr = dict(DATE_FORMATS)[date_fmt](d)
    A = lambda v: sym + fmt_amount(Decimal(str(v)), num_style)  # noqa: E731
    N = lambda v: fmt_amount(Decimal(str(v)), num_style)  # noqa: E731
    qty = lambda v: (f"{v:g}" if num_style != "eu" else f"{v:g}".replace(".", ","))  # noqa: E731

    labels = [
        dict(title="INVOICE", num="Invoice No:", date="Invoice Date:", frm=None, to="Bill To:", cols=("Description", "Qty", "Rate", "Amount"),
             sub="Subtotal", tax="Tax ({r})", tot="Total Due"),
        dict(title="TAX INVOICE", num="Invoice #:", date="Issue Date:", frm="From:", to="Billed To:", cols=("Service", "Hours", "Hourly Rate", "Line Total"),
             sub="Sub-total", tax="VAT {r}", tot="Amount Due"),
        dict(title="BILL", num="Bill No:", date="Date:", frm=None, to="Client:", cols=("Item", "Qty", "Price", "Amount"),
             sub="Net Amount", tax="Sales Tax", tot="Grand Total"),
        dict(title="Statement of Services", num="Invoice Number:", date="Invoice Date:", frm="Provider:", to="Invoice To:", cols=("Particulars", "Units", "Unit Price", "Amount"),
             sub="Subtotal", tax="Tax", tot="Balance Due"),
    ][template]

    rows_per_page = 14
    pages = [pr["line_items"][i : i + rows_per_page] for i in range(0, max(1, len(pr["line_items"])), rows_per_page)] or [[]]
    n_pages = len(pages)
    for pi, rows in enumerate(pages):
        y = H - 60
        c.setFont("Helvetica-Bold", 15)
        if labels["frm"]:
            c.drawString(50, y, labels["title"])
            c.setFont("Helvetica", 10)
            y -= 34
            c.drawString(50, y, labels["frm"])
            c.drawString(120, y, inv["supplier_name"])
            c.drawString(120, y - 13, inv["supplier_address"])
        else:
            c.drawString(50, y, inv["supplier_name"])
            c.setFont("Helvetica", 9)
            c.drawString(50, y - 14, inv["supplier_address"])
            c.setFont("Helvetica-Bold", 18)
            c.drawRightString(W - 50, y, labels["title"])
        c.setFont("Helvetica", 10)
        ry = H - 110
        if not hide_number:
            c.drawString(W - 250, ry, labels["num"])
            c.drawString(W - 150, ry, pr["invoice_number"])
        c.drawString(W - 250, ry - 15, labels["date"])
        c.drawString(W - 150, ry - 15, dstr)
        if template == 3:
            c.drawString(W - 250, ry - 30, "Service Period:")
            sp = d - timedelta(days=30)
            c.drawString(W - 150, ry - 30, f"{dict(DATE_FORMATS)[date_fmt](sp)} - {dict(DATE_FORMATS)[date_fmt](d - timedelta(days=1))}")
        if template == 0:
            c.drawString(W - 250, ry - 30, "Due Date:")
            c.drawString(W - 150, ry - 30, dict(DATE_FORMATS)[date_fmt](d + timedelta(days=30)))
        y = H - 175
        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, labels["to"])
        c.setFont("Helvetica", 10)
        c.drawString(50, y - 14, inv["customer_name"])
        c.drawString(50, y - 27, "Accounts Payable Department")
        if n_pages > 1:
            c.drawRightString(W - 50, 30, f"Page {pi + 1} of {n_pages}")

        # table
        y = H - 250
        xs = [50, W - 260, W - 185, W - 50]
        c.setFont("Helvetica-Bold", 10)
        c.drawString(xs[0], y, labels["cols"][0])
        c.drawRightString(xs[1] + 30, y, labels["cols"][1])
        c.drawRightString(xs[2] + 45, y, labels["cols"][2])
        c.drawRightString(xs[3], y, labels["cols"][3])
        c.line(50, y - 5, W - 50, y - 5)
        c.setFont("Helvetica", 10)
        y -= 22
        for it in rows:
            c.drawString(xs[0], y, it["description"])
            c.drawRightString(xs[1] + 30, y, qty(it["quantity"]))
            c.drawRightString(xs[2] + 45, y, N(it["unit_price"]))
            c.drawRightString(xs[3], y, N(it["amount"]))
            y -= 18

        if pi == n_pages - 1:
            y -= 12
            c.line(W - 260, y + 8, W - 50, y + 8)
            rate_txt = f"{inv['tax_rate'] * 100:g}%"
            summary = [(labels["sub"], A(pr["subtotal"]))]
            if pr.get("tax") is not None:
                summary.append((labels["tax"].format(r=rate_txt), A(pr["tax"])))
            summary.append((labels["tot"], A(pr["total"])))
            for k, (lab, val) in enumerate(summary):
                c.setFont("Helvetica-Bold" if k == len(summary) - 1 else "Helvetica", 10)
                c.drawString(W - 260, y - 8, lab)
                c.drawRightString(W - 50, y - 8, val)
                y -= 17
            c.setFont("Helvetica", 8)
            c.drawString(50, 60, "Payment terms: Net 30. Thank you for partnering with us in care.")
        c.showPage()
    c.save()
    return buf.getvalue()


def degrade(img: np.ndarray, quality: str, rng: random.Random) -> np.ndarray:
    if quality == "clean":
        return img
    h, w = img.shape[:2]
    angle = rng.uniform(-1.2, 1.2) if quality == "medium" else rng.uniform(-2.5, 2.5)
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    out = cv2.warpAffine(img, m, (w, h), borderValue=(255, 255, 255))
    k = 3 if quality == "medium" else 5
    out = cv2.GaussianBlur(out, (k, k), 0)
    noise = np.random.default_rng(rng.randint(0, 10**6)).normal(0, 8 if quality == "medium" else 18, out.shape)
    out = np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    if quality == "poor":
        out = cv2.resize(out, None, fx=0.6, fy=0.6, interpolation=cv2.INTER_AREA)
        out = cv2.convertScaleAbs(out, alpha=0.8, beta=25)  # washed-out contrast
    q = 70 if quality == "medium" else 35
    ok, enc = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, q])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR)


def pdf_to_images(pdf: bytes, dpi: int = 150) -> list[np.ndarray]:
    import pymupdf

    doc = pymupdf.open(stream=pdf, filetype="pdf")
    imgs = []
    for p in doc:
        pix = p.get_pixmap(dpi=dpi)
        a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        imgs.append(a[:, :, ::-1].copy())
    return imgs


def images_to_pdf(imgs: list[np.ndarray]) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for im in imgs:
        ok, enc = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 80])
        h, w = im.shape[:2]
        page = doc.new_page(width=w * 72 / 150, height=h * 72 / 150)
        page.insert_image(page.rect, stream=enc.tobytes())
    return doc.tobytes()


def gt_invoice(inv: dict, printed: dict | None = None, hide_number: bool = False) -> dict:
    """Ground truth = what is printed on the document."""
    p = {**inv, **(printed or {})}
    g = {k: p[k] for k in ("invoice_number", "invoice_date", "supplier_name", "customer_name", "subtotal", "tax", "total", "currency")}
    g["line_items"] = copy.deepcopy(p["line_items"])
    if hide_number:
        g["invoice_number"] = None
    return g


# ------------------------------------------------------------------------- main
def generate(out: Path, seed: int, n: int, batch_invoices: int = 40) -> dict:
    rng = random.Random(seed)
    files_dir = out / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    invoices = [make_invoice(rng, i + seed * 1000) for i in range(n)]

    def write(name: str, data: bytes, entry: dict):
        (files_dir / name).write_bytes(data)
        entry["file"] = name
        manifest.append(entry)

    for i, inv in enumerate(invoices):
        template = rng.randrange(4)
        date_fmt = rng.choice([f for f, _ in DATE_FORMATS])
        num_style = "eu" if rng.random() < 0.15 else "us"
        printed: dict = {}
        planted: list[str] = []
        hide = False
        r = rng.random()
        if r < 0.10:  # total does not equal subtotal + tax (digit transposition)
            t = f"{inv['total']:.2f}"
            digits = list(t.replace(".", ""))
            if len(digits) >= 3 and digits[-3] != digits[-4 if len(digits) > 3 else -3]:
                digits[-3], digits[-4] = digits[-4], digits[-3]
            wrong = float("".join(digits[:-2]) + "." + "".join(digits[-2:]))
            if abs(wrong - inv["total"]) < 0.05:
                wrong = round(inv["total"] + 10, 2)
            printed["total"] = wrong
            planted.append("total_mismatch")
        elif r < 0.18 and len(inv["line_items"]) > 1:  # one line amount changed, subtotal not
            items = copy.deepcopy(inv["line_items"])
            items[0]["amount"] = round(items[0]["amount"] + 25, 2)
            printed["line_items"] = items
            planted += ["line_items_mismatch", "line_item_arithmetic"]
        elif r < 0.24:
            hide = True
            planted.append("missing_field")
        elif r < 0.28:
            printed["tax"] = None
            planted.append("missing_field")
            if inv["tax"]:
                planted.append("total_mismatch")
        pdf = render_pdf(inv, template, date_fmt, num_style, hide, printed)
        gt = gt_invoice(inv, printed, hide)
        meta = {"template": template, "date_format": date_fmt, "number_style": num_style, "pages": None}
        fmt = rng.choices(["pdf", "scan_pdf", "jpg", "png", "tiff"], weights=[45, 20, 15, 10, 10])[0]
        quality = "clean" if fmt == "pdf" else rng.choice(["clean", "medium", "medium", "poor"])
        base = f"inv_{i:03d}"
        entry = {"kind": "invoice", "format": fmt, "quality": quality, "expected": "ok", "invoices": [gt],
                 "planted_issues": planted, **meta}
        if fmt == "pdf":
            write(base + ".pdf", pdf, entry)
        else:
            imgs = [degrade(im, quality, rng) for im in pdf_to_images(pdf)]
            if fmt == "scan_pdf" or len(imgs) > 1 and fmt != "tiff":
                entry["format"] = "scan_pdf"
                write(base + "_scan.pdf", images_to_pdf(imgs), entry)
            elif fmt == "tiff":
                from PIL import Image

                pil = [Image.fromarray(im[:, :, ::-1]) for im in imgs]
                b = io.BytesIO()
                pil[0].save(b, format="TIFF", save_all=True, append_images=pil[1:], compression="tiff_lzw")
                write(base + ".tiff", b.getvalue(), entry)
            else:
                ext = ".jpg" if fmt == "jpg" else ".png"
                ok, enc = cv2.imencode(ext, imgs[0])
                write(base + ext, enc.tobytes(), entry)

    # duplicates: re-send two invoices as separate files (expected duplicate flag)
    dup_sources = rng.sample([m for m in manifest if m["format"] == "pdf" and m["invoices"][0]["invoice_number"]], k=2)
    for k, src in enumerate(dup_sources):
        data = (files_dir / src["file"]).read_bytes()
        e = copy.deepcopy(src)
        e["planted_issues"] = ["duplicate_invoice"]
        e["duplicate_of"] = src["file"]
        write(f"dup_{k}_" + src["file"], data, e)

    # ledgers: the accounts team's spreadsheet of the same invoices, with planted
    # data-entry errors that cross-verification should catch
    ledger_rows, altered = [], []
    for m in manifest:
        if m["kind"] != "invoice" or "dup_" in m["file"]:
            continue
        g = m["invoices"][0]
        if not g["invoice_number"]:
            continue
        row = {"Invoice No": g["invoice_number"], "Invoice Date": g["invoice_date"], "Vendor": g["supplier_name"],
               "Customer": g["customer_name"], "Net Amount": g["subtotal"], "Tax": g["tax"] if g["tax"] is not None else 0.0,
               "Total": g["total"], "Currency": g["currency"], "Source File": m["file"]}
        x = rng.random()
        if x < 0.12:
            t = f"{g['total']:.2f}"
            row["Total"] = float(t[:-4] + t[-3] + t[-4] + t[-2:]) if len(t) > 4 and t[-4] != t[-3] and t[-3] != "." else round(g["total"] + 100, 2)
            altered.append({"invoice_number": g["invoice_number"], "field": "total"})
        elif x < 0.18:
            row["Invoice Date"] = (date.fromisoformat(g["invoice_date"]) + timedelta(days=1)).isoformat()
            altered.append({"invoice_number": g["invoice_number"], "field": "invoice_date"})
        ledger_rows.append(row)
    rng.shuffle(ledger_rows)
    extra = {"Invoice No": "INV-2026-9999", "Invoice Date": "2026-05-05", "Vendor": "Unknown Vendor Ltd", "Customer": "Riverside Senior Living",
             "Net Amount": 100.0, "Tax": 0.0, "Total": 100.0, "Currency": "USD", "Source File": "(no document)"}
    ledger_rows.append(extra)
    ledger_gt = [
        {"invoice_number": r["Invoice No"], "invoice_date": r["Invoice Date"], "supplier_name": r["Vendor"], "customer_name": r["Customer"],
         "subtotal": r["Net Amount"], "tax": r["Tax"], "total": r["Total"], "currency": r["Currency"], "line_items": []}
        for r in ledger_rows
    ]
    import pandas as pd

    df = pd.DataFrame(ledger_rows)
    b = io.BytesIO()
    with pd.ExcelWriter(b, engine="openpyxl") as xw:
        pd.DataFrame([["Accounts Payable Ledger - FY2026"], ["Exported from ERP"]]).to_excel(xw, sheet_name="Cover", header=False, index=False)
        df.to_excel(xw, sheet_name="AP Ledger", index=False)
        items = []
        for m in manifest[:6]:
            g = m["invoices"][0]
            for li in g["line_items"]:
                items.append({"Invoice No": g["invoice_number"], "Description": li["description"], "Qty": li["quantity"],
                              "Unit Price": li["unit_price"], "Line Total": li["amount"]})
        pd.DataFrame(items).to_excel(xw, sheet_name="Line Items", index=False)
    write("ledger_ap_2026.xlsx", b.getvalue(),
          {"kind": "ledger", "format": "xlsx", "expected": "ok", "invoices": ledger_gt, "altered_rows": altered,
           "sheets": ["Cover", "AP Ledger", "Line Items"], "planted_issues": []})
    write("ledger_ap_2026.csv", df.to_csv(index=False).encode(),
          {"kind": "ledger", "format": "csv", "expected": "ok", "invoices": ledger_gt, "altered_rows": altered, "planted_issues": []})
    import xlwt

    wb = xlwt.Workbook()
    ws = wb.add_sheet("Ledger")
    sub = df.head(15)
    for j, col in enumerate(sub.columns):
        ws.write(0, j, col)
    for i2, row in enumerate(sub.itertuples(index=False), start=1):
        for j, v in enumerate(row):
            ws.write(i2, j, v)
    xb = io.BytesIO()
    wb.save(xb)
    write("ledger_q1.xls", xb.getvalue(),
          {"kind": "ledger", "format": "xls", "expected": "ok", "invoices": ledger_gt[:15], "planted_issues": []})

    # multi-invoice batch PDF (tests splitting)
    import pymupdf

    batch = pymupdf.open()
    batch_gt = []
    for k in range(batch_invoices):
        inv = make_invoice(rng, 50_000 + seed * 1000 + k)
        pdf = render_pdf(inv, rng.randrange(4), rng.choice([f for f, _ in DATE_FORMATS]), "us")
        batch.insert_pdf(pymupdf.open(stream=pdf, filetype="pdf"))
        batch_gt.append(gt_invoice(inv))
    write("batch_multi_invoice.pdf", batch.tobytes(),
          {"kind": "batch", "format": "pdf", "expected": "ok", "invoices": batch_gt, "planted_issues": [], "pages": batch.page_count})

    # corrupted / invalid files (expected: fail gracefully with a clear code)
    good_pdf = (files_dir / manifest[0]["file"]).read_bytes() if manifest[0]["file"].endswith(".pdf") else render_pdf(invoices[0], 0, "iso", "us")
    corrupt = [
        ("corrupt_random.pdf", bytes(rng.getrandbits(8) for _ in range(4000)), "corrupted_file"),
        ("corrupt_empty.png", b"", "empty_file"),
        ("corrupt_header_only.pdf", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", "corrupted_file"),
        ("corrupt_truncated.jpg", cv2.imencode(".jpg", np.full((400, 300, 3), 255, np.uint8))[1].tobytes()[:300], "corrupted_file"),
        ("corrupt_bad_zip.xlsx", b"PK\x03\x04" + bytes(rng.getrandbits(8) for _ in range(500)), "corrupted_file"),
        ("corrupt_blank_scan.png", cv2.imencode(".png", np.full((1100, 850, 3), 255, np.uint8))[1].tobytes(), "no_text_found"),
    ]
    for name, data, code in corrupt:
        write(name, data, {"kind": "corrupt", "format": name.rsplit(".", 1)[1], "expected": "fail", "expected_error": code, "invoices": [], "planted_issues": []})
    # a truncated-but-repairable PDF is a realistic case: should be processed partially or fail cleanly
    write("damaged_truncated.pdf", good_pdf[: int(len(good_pdf) * 0.7)],
          {"kind": "corrupt", "format": "pdf", "expected": "any", "invoices": [], "planted_issues": []})

    meta = {"seed": seed, "n_invoices": n, "files": manifest}
    (out / "manifest.json").write_text(json.dumps(meta, indent=1))
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--batch", type=int, default=40)
    a = ap.parse_args()
    m = generate(Path(a.out), a.seed, a.n, a.batch)
    print(f"wrote {len(m['files'])} files to {a.out}")
