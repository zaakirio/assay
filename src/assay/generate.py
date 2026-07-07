"""Golden dataset generator: synthetic supplier invoices as PDFs plus ground
truth JSON. Deterministic for a given seed so the golden set is reproducible
and reviewable in git. No real company names."""

import json
import random
import zlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

VENDORS = [
    ("Northwind Fastener Supply Ltd", "14 Foundry Lane, Sheffield S3 8DN, United Kingdom", "GBP", "£"),
    ("Kestrel Logistics GmbH", "Hafenstraße 22, 20457 Hamburg, Germany", "EUR", "€"),
    ("Blue Mesa Packaging Co.", "4410 Industrial Pkwy, Tucson, AZ 85714, USA", "USD", "$"),
    ("Yarrabee Office Interiors Pty Ltd", "88 Gipps St, Collingwood VIC 3066, Australia", "AUD", "$"),
    ("Hokusei Precision Tools KK", "2-14-6 Kiba, Koto-ku, Tokyo 135-0042, Japan", "JPY", "¥"),
    ("Valmont & Cie Reprographie", "17 rue des Ateliers, 69003 Lyon, France", "EUR", "€"),
    ("Cedar Hollow Catering LLC", "902 Birchwood Ave, Portland, OR 97217, USA", "USD", "$"),
    ("Silberhorn Kalibrierdienst AG", "Werkstrasse 9, 8404 Winterthur, Switzerland", "CHF", "CHF"),
    ("Marlin Bay Marine Services", "Unit 3, 51 Quayside Dr, Auckland 1010, New Zealand", "NZD", "$"),
    ("Tarnowski Metalworks Sp. z o.o.", "ul. Odlewnicza 12, 41-100 Siemianowice, Poland", "EUR", "€"),
    ("Redfern & Gale Stationers", "230 Chandlery Row, Bristol BS1 4QA, United Kingdom", "GBP", "£"),
    ("Ostrander Freight Systems Inc.", "77 Dockside Blvd, Newark, NJ 07105, USA", "USD", "$"),
]

PRODUCTS = [
    ("M6 hex bolts, zinc plated (box 500)", 8.40, 60.0),
    ("Pallet wrap, 500mm x 300m", 12.95, 30.0),
    ("A4 copier paper, 80gsm (5 ream box)", 21.50, 12.0),
    ("Nitrile gloves, size L (box 100)", 9.20, 25.0),
    ("Thermal transfer labels 4x6 (roll)", 17.80, 10.0),
    ("HDPE crate 600x400x320", 14.25, 40.0),
    ("Laser toner cartridge CX-410 black", 88.00, 3.0),
    ("Anti-static bubble wrap 1.2m x 50m", 33.10, 6.0),
    ("Stainless worktop bracket 300mm", 6.75, 80.0),
    ("Machine coolant concentrate 20L", 74.50, 4.0),
    ("Warehouse marking tape, yellow 75mm", 5.60, 24.0),
    ("Two-way radio battery pack NX-220", 41.90, 5.0),
    ("Calibration service, torque wrench", 55.00, 2.0),
    ("Freight surcharge, fuel adjustment", 28.00, 1.0),
    ("Site delivery and unloading", 65.00, 1.0),
    ("Espresso beans, dark roast 1kg", 18.40, 15.0),
    ("Sandwich platter, mixed (serves 10)", 52.00, 4.0),
    ("Ergonomic task chair, charcoal", 189.00, 6.0),
    ("Desk riser, dual monitor", 96.50, 8.0),
    ("Cable tray 2m galvanised", 11.30, 35.0),
]

TAX_LABELS = {"GBP": "VAT 20%", "EUR": "VAT 19%", "USD": "Sales Tax 8.5%",
              "AUD": "GST 10%", "JPY": "Consumption Tax 10%", "CHF": "MwSt 8.1%",
              "NZD": "GST 15%"}
TAX_RATES = {"GBP": 0.20, "EUR": 0.19, "USD": 0.085, "AUD": 0.10, "JPY": 0.10,
             "CHF": 0.081, "NZD": 0.15}

DATE_FORMATS = ["iso", "dmy_slash", "mdy_slash", "dmy_dot", "d_mon_y", "mon_d_y"]


def format_date(d: date, style: str) -> str:
    if style == "iso":
        return d.isoformat()
    if style == "dmy_slash":
        return d.strftime("%d/%m/%Y")
    if style == "mdy_slash":
        return d.strftime("%m/%d/%Y")
    if style == "dmy_dot":
        return d.strftime("%d.%m.%Y")
    if style == "d_mon_y":
        return f"{d.day} {d.strftime('%b %Y')}"
    return d.strftime("%B %-d, %Y")


def money(amount: float, cur: str, symbol: str) -> str:
    if cur == "JPY":
        return f"{symbol}{amount:,.0f}"
    return f"{symbol}{amount:,.2f}"


@dataclass
class Item:
    description: str
    quantity: float
    unit_price: float
    amount: float


@dataclass
class Spec:
    doc_id: str
    template: int
    vendor: str
    vendor_address: str
    currency: str
    symbol: str
    invoice_number: str
    invoice_date: date | None
    due_date: date | None
    date_style: str
    items: list[Item]
    subtotal: float
    tax: float | None
    total: float
    tax_label: str
    show_subtotal: bool = True
    show_due: bool = True
    show_currency_code: bool = True
    typo_labels: bool = False
    handwritten_note: str | None = None
    ambiguous: bool = False
    ambiguity_kind: str | None = None
    notes: list[str] = field(default_factory=list)


def _round(v: float, cur: str) -> float:
    return float(round(v)) if cur == "JPY" else round(v, 2)


def build_specs(rng: random.Random, count: int) -> list[Spec]:
    specs = []
    for i in range(count):
        doc_id = f"inv_{i + 1:03d}"
        vendor, addr, cur, sym = VENDORS[i % len(VENDORS)]
        template = i % 5
        # JPY prices scaled up so line values look plausible in yen.
        scale = 150.0 if cur == "JPY" else 1.0

        n_items = rng.choice([1, 2, 3, 3, 4, 5, 6])
        multi_page = i in (7, 19)
        if multi_page:
            n_items = rng.randint(44, 52)
        items = []
        for prod, price, maxq in rng.sample(PRODUCTS, k=min(n_items, len(PRODUCTS))) * (
            3 if n_items > len(PRODUCTS) else 1
        ):
            if len(items) >= n_items:
                break
            qty = float(rng.randint(1, max(1, int(maxq))))
            unit = _round(price * scale * rng.uniform(0.9, 1.15), cur)
            items.append(Item(prod, qty, unit, _round(qty * unit, cur)))

        subtotal = _round(sum(it.amount for it in items), cur)
        has_tax = rng.random() > 0.2
        tax = _round(subtotal * TAX_RATES[cur], cur) if has_tax else None
        total = _round(subtotal + (tax or 0.0), cur)

        inv_date = date(2026, rng.randint(1, 6), rng.randint(1, 28))
        due = inv_date + timedelta(days=rng.choice([14, 30, 30, 45, 60]))

        num_style = rng.choice(["INV-{:05d}", "2026-{:04d}", "SI/{:06d}", "{:07d}", "IN{:05d}A"])
        spec = Spec(
            doc_id=doc_id,
            template=template,
            vendor=vendor,
            vendor_address=addr,
            currency=cur,
            symbol=sym,
            invoice_number=num_style.format(rng.randint(100, 99999)),
            invoice_date=inv_date,
            due_date=due,
            date_style=rng.choice(DATE_FORMATS),
            items=items,
            subtotal=subtotal,
            tax=tax,
            total=total,
            tax_label=TAX_LABELS[cur],
        )
        if rng.random() < 0.25:
            spec.show_due = False
            spec.due_date = None
        if rng.random() < 0.3:
            spec.typo_labels = True
        if rng.random() < 0.25:
            spec.handwritten_note = rng.choice([
                "Approved for payment - K.M.",
                "chase PO number w/ Dave",
                "paid?? check remittance",
                "OK to post - 2nd reminder sent",
            ])
        if rng.random() < 0.3:
            spec.notes.append(rng.choice([
                "Please quote the invoice number on all payments.",
                "Goods remain our property until paid in full.",
                "Bank transfer preferred. Late payments incur 2% monthly interest.",
                "Thank you for your continued business.",
            ]))
        specs.append(spec)

    if count > 11:
        # One invoice with no printed invoice date at all.
        specs[11].invoice_date = None
        specs[11].due_date = None
        specs[11].show_due = False
    if count > 14:
        # One with subtotal hidden (only total printed).
        specs[14].show_subtotal = False

    # Three genuinely ambiguous documents.
    # inv_004: Australian vendor, "$" symbol, no currency code anywhere.
    if count > 3:
        a = specs[3]
        a.show_currency_code = False
        a.ambiguous = True
        a.ambiguity_kind = "currency_symbol_only"
        a.notes.append("All amounts in dollars.")

    # inv_010: two dates printed with no labels; issue vs due is a guess.
    if count > 9:
        b = specs[9]
        b.ambiguous = True
        b.ambiguity_kind = "unlabeled_dates"
        if b.due_date is None:
            b.due_date = b.invoice_date + timedelta(days=30)

    # inv_023: 'TOTAL' printed against the pre-tax figure, grand total only as
    # 'Amount Due'; which one is the total is genuinely confusable.
    if count > 22:
        c = specs[22]
        c.ambiguous = True
        c.ambiguity_kind = "conflicting_totals"

    return specs


# --- rendering -------------------------------------------------------------

def _hand(c: Canvas, x: float, y: float, text: str, rot: float = 4):
    c.saveState()
    c.translate(x, y)
    c.rotate(rot)
    c.setFont("Courier-Oblique", 11)
    c.setFillColorRGB(0.15, 0.2, 0.55)
    c.drawString(0, 0, text)
    c.restoreState()


def _labels(spec: Spec) -> dict:
    if spec.typo_labels:
        return {"invno": "Invocie No.", "date": "Inovice Date", "due": "Due Dtae",
                "qty": "Qauntity", "desc": "Descripton", "unit": "Unit Prcie",
                "amount": "Amonut", "subtotal": "Sub-totl", "total": "Ttoal Due"}
    return {"invno": "Invoice No.", "date": "Invoice Date", "due": "Due Date",
            "qty": "Qty", "desc": "Description", "unit": "Unit Price",
            "amount": "Amount", "subtotal": "Subtotal", "total": "Total Due"}


_BOLD = {"Helvetica": "Helvetica-Bold", "Times-Roman": "Times-Bold",
         "Courier": "Courier-Bold"}


def _items_table(c: Canvas, spec: Spec, x: float, y: float, width: float,
                 font: str, size: float, page_bottom: float,
                 new_page) -> float:
    lab = _labels(spec)
    col_desc, col_qty, col_unit = x, x + width * 0.58, x + width * 0.72
    col_amt = x + width * 0.88
    c.setFont(_BOLD[font], size)
    for cx, t in ((col_desc, lab["desc"]), (col_qty, lab["qty"]),
                  (col_unit, lab["unit"]), (col_amt, lab["amount"])):
        c.drawString(cx, y, t)
    y -= size * 0.6
    c.line(x, y, x + width, y)
    y -= size * 1.4
    c.setFont(font, size)
    for it in spec.items:
        if y < page_bottom:
            c.showPage()
            y = new_page(c)
            c.setFont(font, size)
        c.drawString(col_desc, y, it.description[:52])
        c.drawRightString(col_qty + 24, y, f"{it.quantity:g}")
        c.drawRightString(col_unit + 40, y, money(it.unit_price, spec.currency, ""))
        c.drawRightString(col_amt + 40, y, money(it.amount, spec.currency, ""))
        y -= size * 1.5
    return y


def _totals_block(c: Canvas, spec: Spec, x_label: float, x_val: float, y: float,
                  font: str, size: float) -> float:
    lab = _labels(spec)
    rows = []
    if spec.show_subtotal:
        rows.append((lab["subtotal"], spec.subtotal))
    if spec.tax is not None:
        rows.append((spec.tax_label, spec.tax))
    if spec.ambiguity_kind == "conflicting_totals":
        rows = [("TOTAL", spec.subtotal)]
        if spec.tax is not None:
            rows.append((spec.tax_label, spec.tax))
        rows.append(("Amount Due", spec.total))
    else:
        rows.append((lab["total"], spec.total))
    for i, (label, val) in enumerate(rows):
        bold = i == len(rows) - 1
        c.setFont(_BOLD[font] if bold else font, size + (1 if bold else 0))
        c.drawString(x_label, y, label)
        c.drawRightString(x_val, y, money(val, spec.currency, spec.symbol))
        y -= size * 1.6
    return y


def _meta_lines(spec: Spec) -> list[tuple[str, str]]:
    lab = _labels(spec)
    out = [(lab["invno"], spec.invoice_number)]
    if spec.ambiguity_kind == "unlabeled_dates":
        out.append(("", format_date(spec.invoice_date, spec.date_style)))
        out.append(("", format_date(spec.due_date, spec.date_style)))
        return out
    if spec.invoice_date:
        out.append((lab["date"], format_date(spec.invoice_date, spec.date_style)))
    if spec.show_due and spec.due_date:
        out.append((lab["due"], format_date(spec.due_date, spec.date_style)))
    if spec.show_currency_code:
        out.append(("Currency", spec.currency))
    return out


def render_pdf(spec: Spec, path: Path):
    c = Canvas(str(path), pagesize=A4 if spec.template % 2 else letter, invariant=1)
    pw, ph = (A4 if spec.template % 2 else letter)
    margin = 18 * mm
    render = [_t_classic, _t_banner, _t_grid, _t_receipt, _t_letterhead][spec.template]
    render(c, spec, pw, ph, margin)
    if spec.handwritten_note:
        _hand(c, margin + 30, 24 * mm, spec.handwritten_note, rot=rot_for(spec))
    c.save()


def rot_for(spec: Spec) -> float:
    # Not hash(): that is randomized per process and would break the
    # byte-identical-across-runs guarantee for the golden PDFs.
    return 3 + (zlib.crc32(spec.doc_id.encode()) % 5)


def _t_classic(c, spec, pw, ph, m):
    y = ph - m
    c.setFont("Helvetica-Bold", 15)
    c.drawString(m, y, spec.vendor)
    c.setFont("Helvetica", 9)
    for line in spec.vendor_address.split(", "):
        y -= 12
        c.drawString(m, y, line)
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(pw - m, ph - m, "INVOICE")
    ym = ph - m - 30
    c.setFont("Helvetica", 10)
    for label, val in _meta_lines(spec):
        c.drawRightString(pw - m - 90, ym, label)
        c.drawRightString(pw - m, ym, val)
        ym -= 14
    y = min(y, ym) - 40

    def new_page(cv):
        cv.setFont("Helvetica", 8)
        cv.drawString(m, ph - m, f"{spec.vendor} - invoice {spec.invoice_number} (continued)")
        return ph - m - 30

    y = _items_table(c, spec, m, y, pw - 2 * m, "Helvetica", 9.5, m + 60, new_page)
    y -= 10
    _totals_block(c, spec, pw - m - 170, pw - m, y, "Helvetica", 10)
    c.setFont("Helvetica", 8)
    yn = m + 10
    for n in spec.notes:
        c.drawString(m, yn, n)
        yn += 10


def _t_banner(c, spec, pw, ph, m):
    c.setFillColorRGB(0.13, 0.3, 0.45)
    c.rect(0, ph - 26 * mm, pw, 26 * mm, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(m, ph - 15 * mm, spec.vendor)
    c.setFont("Helvetica", 9)
    c.drawString(m, ph - 20 * mm, spec.vendor_address)
    c.setFillColorRGB(0, 0, 0)
    y = ph - 36 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(m, y, "TAX INVOICE")
    c.setFont("Helvetica", 10)
    x2 = pw / 2
    ym = y
    for label, val in _meta_lines(spec):
        c.drawString(x2, ym, f"{label}  {val}".strip())
        ym -= 13
    y = ym - 20

    def new_page(cv):
        return ph - m - 20

    y = _items_table(c, spec, m, y, pw - 2 * m, "Helvetica", 9.5, m + 60, new_page)
    _totals_block(c, spec, pw - m - 180, pw - m, y - 8, "Helvetica", 10)
    c.setFont("Helvetica-Oblique", 8)
    yn = m
    for n in spec.notes:
        c.drawString(m, yn, n)
        yn += 10


def _t_grid(c, spec, pw, ph, m):
    y = ph - m
    c.setFont("Times-Bold", 14)
    c.drawString(m, y, spec.vendor.upper())
    c.setFont("Times-Roman", 9)
    c.drawString(m, y - 12, spec.vendor_address)
    meta = _meta_lines(spec)
    box_h = 16
    bw = (pw - 2 * m) / len(meta)
    yb = y - 40
    for i, (label, val) in enumerate(meta):
        x = m + i * bw
        c.rect(x, yb - box_h, bw, box_h * 2)
        c.setFont("Times-Bold", 8)
        c.drawCentredString(x + bw / 2, yb + 4, label or "Date")
        c.setFont("Times-Roman", 9)
        c.drawCentredString(x + bw / 2, yb - 10, val)
    y = yb - box_h - 26

    def new_page(cv):
        return ph - m - 20

    y = _items_table(c, spec, m, y, pw - 2 * m, "Times-Roman", 9.5, m + 70, new_page)
    _totals_block(c, spec, pw - m - 160, pw - m, y - 10, "Times-Roman", 10)
    c.setFont("Times-Italic", 8)
    yn = m + 8
    for n in spec.notes:
        c.drawString(m, yn, n)
        yn += 10


def _t_receipt(c, spec, pw, ph, m):
    cx = pw / 2
    y = ph - m
    c.setFont("Courier-Bold", 12)
    c.drawCentredString(cx, y, spec.vendor)
    c.setFont("Courier", 8)
    y -= 11
    c.drawCentredString(cx, y, spec.vendor_address)
    y -= 20
    c.setFont("Courier", 9)
    for label, val in _meta_lines(spec):
        c.drawCentredString(cx, y, f"{label} {val}".strip())
        y -= 12
    y -= 10
    c.drawCentredString(cx, y, "-" * 60)
    y -= 16
    x = m + 30 * mm if pw > 500 else m

    def new_page(cv):
        return ph - m

    y = _items_table(c, spec, x, y, pw - 2 * x, "Courier", 8.5, m + 60, new_page)
    c.setFont("Courier", 9)
    c.drawCentredString(cx, y, "-" * 60)
    y -= 16
    _totals_block(c, spec, x + 40, x + (pw - 2 * x) - 20, y, "Courier", 9)
    yn = m
    c.setFont("Courier", 7)
    for n in spec.notes:
        c.drawCentredString(cx, yn, n)
        yn += 9


def _t_letterhead(c, spec, pw, ph, m):
    y = ph - m
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(pw / 2, y, spec.vendor)
    c.setFont("Helvetica", 9)
    c.drawCentredString(pw / 2, y - 14, spec.vendor_address)
    c.line(m, y - 24, pw - m, y - 24)
    y -= 48
    c.setFont("Helvetica", 10)
    parts = [f"{label}: {val}" if label else val for label, val in _meta_lines(spec)]
    c.drawString(m, y, "Invoice detail    " + "    ".join(parts))
    y -= 30

    def new_page(cv):
        return ph - m - 20

    y = _items_table(c, spec, m, y, pw - 2 * m, "Helvetica", 9.5, m + 70, new_page)
    _totals_block(c, spec, pw - m - 170, pw - m, y - 10, "Helvetica", 10)
    c.setFont("Helvetica", 8)
    yn = m + 8
    for n in spec.notes:
        c.drawString(m, yn, n)
        yn += 10


# --- ground truth ----------------------------------------------------------

def truth_json(spec: Spec) -> dict:
    return {
        "doc_id": spec.doc_id,
        "template": spec.template,
        "ambiguous": spec.ambiguous,
        "ambiguity_kind": spec.ambiguity_kind,
        "expected_route": "review" if spec.ambiguous else "auto",
        "invoice": {
            "vendor": spec.vendor,
            "invoice_number": spec.invoice_number,
            "invoice_date": spec.invoice_date.isoformat() if spec.invoice_date else None,
            "due_date": spec.due_date.isoformat() if (spec.show_due or spec.ambiguity_kind == "unlabeled_dates") and spec.due_date else None,
            "currency": spec.currency,
            "line_items": [
                {"description": it.description, "quantity": it.quantity,
                 "unit_price": it.unit_price, "amount": it.amount}
                for it in spec.items
            ],
            "subtotal": spec.subtotal if spec.show_subtotal or spec.ambiguity_kind == "conflicting_totals" else None,
            "tax": spec.tax,
            "total": spec.total,
        },
    }


def generate(out_dir: Path, count: int = 32, seed: int = 42) -> list[Path]:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = build_specs(rng, count)
    paths = []
    for spec in specs:
        pdf = out_dir / f"{spec.doc_id}.pdf"
        render_pdf(spec, pdf)
        (out_dir / f"{spec.doc_id}.truth.json").write_text(
            json.dumps(truth_json(spec), indent=2, ensure_ascii=False) + "\n"
        )
        paths.append(pdf)
    return paths
