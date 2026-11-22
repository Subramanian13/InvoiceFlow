from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "demo" / "fixtures"


def atlas_invoice(path: Path, *, invoice_number: str, po: str | None, vendor: str = "Atlas Transport LLC", tax_id: str = "12-3454107",
                  shipment: str = "SH-8891", base_quantity: str = "1", base_uom: str = "TRIP", base_rate: str = "2,000.00",
                  detention_hours: str | None = "3", detention_rate: str = "200.00"):
    c = canvas.Canvas(str(path), pagesize=LETTER)
    width, height = LETTER
    c.setFillColor(colors.HexColor("#173d31")); c.rect(0, height - 118, width, 118, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 21 if len(vendor) > 22 else 25); c.drawString(48, height - 58, vendor.upper())
    c.setFont("Helvetica", 9); c.drawString(48, height - 79, "450 Harbor Way, Newark, NJ 07114 | EIN " + tax_id)
    c.setFillColor(colors.HexColor("#173d31")); c.setFont("Helvetica-Bold", 18); c.drawRightString(width - 48, height - 158, "INVOICE")
    c.setFont("Helvetica", 10); c.drawString(48, height - 175, "Bill to: GlobalFreight Inc.")
    details = [("Invoice number", invoice_number), ("Invoice date", "November 1, 2026"), ("Due date", "December 1, 2026"), ("PO reference", po or "Not provided"), ("Shipment", shipment), ("Currency", "USD")]
    y = height - 205
    for label, value in details:
        c.setFillColor(colors.HexColor("#6a756f")); c.drawString(48, y, label)
        c.setFillColor(colors.HexColor("#15231e")); c.setFont("Helvetica-Bold", 10); c.drawString(148, y, value); c.setFont("Helvetica", 10); y -= 20
    y -= 18; c.setFillColor(colors.HexColor("#edf3ef")); c.rect(48, y, width - 96, 28, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#173d31")); c.setFont("Helvetica-Bold", 9)
    for x, text in [(58, "DESCRIPTION"), (354, "QTY"), (410, "RATE"), (505, "AMOUNT")]: c.drawString(x, y + 10, text)
    base_amount = float(base_quantity) * float(base_rate.replace(",", ""))
    rows = [(f"Base freight - shipment {shipment}", f"{base_quantity} {base_uom}", f"${base_rate}", f"${base_amount:,.2f}")]
    detention_amount = 0.0
    if detention_hours is not None:
        detention_amount = float(detention_hours) * float(detention_rate.replace(",", ""))
        rows.append((f"Detention - {detention_hours} billable hours - {shipment}", f"{detention_hours} HR", f"${detention_rate}", f"${detention_amount:,.2f}"))
    y -= 28; c.setFont("Helvetica", 10)
    for description, qty, rate, amount in rows:
        c.setFillColor(colors.HexColor("#15231e")); c.drawString(58, y, description); c.drawString(354, y, qty); c.drawString(410, y, rate); c.drawRightString(width - 58, y, amount); y -= 30
    c.setStrokeColor(colors.HexColor("#cdd8d1")); c.line(340, y, width - 48, y); y -= 24
    total = base_amount + detention_amount
    for label, amount, bold in [("Subtotal", f"${total:,.2f}", False), ("Tax", "$0.00", False), ("TOTAL DUE", f"${total:,.2f} USD", True)]:
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 11); c.drawString(360, y, label); c.drawRightString(width - 48, y, amount); y -= 22
    c.setFont("Helvetica", 8); c.setFillColor(colors.HexColor("#738078")); c.drawString(48, 52, "Synthetic case-study invoice. No payment is requested.")
    c.save()


def pacific_invoice(path: Path):
    c = canvas.Canvas(str(path), pagesize=LETTER); width, height = LETTER
    c.setFillColor(colors.HexColor("#17486f")); c.rect(40, 38, 11, height - 76, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#17486f")); c.setFont("Times-Bold", 28); c.drawString(78, height - 72, "Pacific Freight Inc.")
    c.setFont("Helvetica", 9); c.setFillColor(colors.HexColor("#657482")); c.drawString(78, height - 92, "88 Coastline Drive | Oakland, CA 94607 | EIN 98-7658821")
    c.setFont("Times-Bold", 38); c.setFillColor(colors.HexColor("#d8e7f1")); c.drawRightString(width - 44, height - 74, "INVOICE")
    c.setFillColor(colors.HexColor("#1d2c37")); c.setFont("Helvetica-Bold", 10)
    for y, label, value in [(height-150,"INVOICE #","INV-777"),(height-174,"DATE","11/05/2026"),(height-198,"SHIPMENT","SH-7777"),(height-222,"PO NUMBER","Not supplied")]:
        c.drawString(78,y,label); c.setFont("Helvetica",10); c.drawString(178,y,value); c.setFont("Helvetica-Bold",10)
    c.setFillColor(colors.HexColor("#17486f")); c.rect(78, height-300, width-122, 30, fill=1, stroke=0); c.setFillColor(colors.white); c.drawString(90,height-289,"SERVICE"); c.drawString(382,height-289,"QTY / RATE"); c.drawRightString(width-56,height-289,"AMOUNT")
    c.setFillColor(colors.HexColor("#1d2c37")); c.setFont("Helvetica",10); c.drawString(90,height-332,"Regional drayage - standard service - SH-7777"); c.drawString(382,height-332,"1 trip x $1,000"); c.drawRightString(width-56,height-332,"$1,000.00")
    c.setFont("Helvetica-Bold",12); c.drawString(382,height-390,"TOTAL USD"); c.drawRightString(width-56,height-390,"$1,000.00")
    c.setFont("Helvetica",8); c.setFillColor(colors.HexColor("#73808a")); c.drawString(78,52,"Synthetic case-study invoice. PO intentionally omitted for matching review."); c.save()


def scanned_invoice(path: Path):
    image = Image.new("RGB", (1275, 1650), "#f8f5ed"); draw = ImageDraw.Draw(image)
    try: title = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 46); body = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 25); bold = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 28)
    except OSError: title = body = bold = ImageFont.load_default()
    draw.rectangle((55, 60, 1220, 220), fill="#283f35"); draw.text((95, 105), "ATLAS TRANSPORT LLC", fill="white", font=title)
    draw.text((85, 275), "SCANNED INVOICE", fill="#283f35", font=title)
    lines = ["Invoice: INV-504-SCAN", "Invoice date: 11/01/2026", "PO: PO-10045", "Shipment: SH-8891", "Currency: USD", "", "Base freight     1 trip x $2,000.00     $2,000.00", "Detention        3 hours x $200.00       $600.00", "", "Subtotal: $2,600.00", "Tax: $0.00", "TOTAL: $2,600.00"]
    y = 380
    for line in lines: draw.text((90,y), line, fill="#242b27", font=bold if "TOTAL:" in line else body); y += 68
    draw.text((90,1530), "Synthetic raster-only case-study document", fill="#727872", font=body)
    image.save(path, "PDF", resolution=150.0)


def business_invoice(path: Path, *, vendor: str, address: str, tax_id: str, invoice_number: str,
                     po: str | None, shipment: str, currency: str, description: str,
                     quantity: str, uom: str, rate: str, line_amount: str,
                     subtotal: str, tax: str, total: str, accent: str = "#243d5a",
                     extra_line: tuple[str, str, str, str] | None = None):
    c = canvas.Canvas(str(path), pagesize=LETTER); width, height = LETTER
    c.setFillColor(colors.HexColor(accent)); c.rect(36, height - 104, width - 72, 68, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 20); c.drawString(54, height - 69, vendor)
    c.setFont("Helvetica", 8); c.drawString(54, height - 88, f"{address} | Tax ID {tax_id}")
    c.setFillColor(colors.HexColor("#1d2923")); c.setFont("Helvetica-Bold", 26); c.drawRightString(width - 48, height - 142, "INVOICE")
    details = [("Invoice number", invoice_number), ("Invoice date", "November 10, 2026"),
               ("Due date", "December 10, 2026"), ("PO reference", po or "Not provided"),
               ("Shipment", shipment), ("Currency", currency)]
    y = height - 174
    for label, value in details:
        c.setFont("Helvetica", 9); c.setFillColor(colors.HexColor("#64716a")); c.drawString(54, y, label)
        c.setFont("Helvetica-Bold", 9); c.setFillColor(colors.HexColor("#1d2923")); c.drawString(145, y, value); y -= 18
    y -= 18; c.setFillColor(colors.HexColor(accent)); c.rect(54, y, width - 108, 26, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 8)
    for x, label in [(64, "DESCRIPTION"), (346, "QUANTITY"), (425, "RATE"), (520, "AMOUNT")]: c.drawString(x, y + 9, label)
    rows = [(description, f"{quantity} {uom}", f"{currency} {rate}", f"{currency} {line_amount}")]
    if extra_line: rows.append(extra_line)
    y -= 28; c.setFont("Helvetica", 9); c.setFillColor(colors.HexColor("#1d2923"))
    for desc, qty, unit_rate, amount in rows:
        c.drawString(64, y, desc); c.drawString(346, y, qty); c.drawString(425, y, unit_rate); c.drawRightString(width - 54, y, amount); y -= 28
    c.setStrokeColor(colors.HexColor("#ccd5d0")); c.line(338, y, width - 54, y); y -= 23
    for label, value, bold in [("Subtotal", subtotal, False), ("Tax", tax, False), ("TOTAL", total, True)]:
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10); c.drawString(380, y, label); c.drawRightString(width - 54, y, f"{currency} {value}"); y -= 20
    c.setFont("Helvetica", 8); c.setFillColor(colors.HexColor("#77827c")); c.drawString(54, 46, "Synthetic InvoiceFlow demonstration document. No payment is requested.")
    c.save()


def handwritten_invoice(path: Path):
    image = Image.new("RGB", (1275, 1650), "#fffdf4"); draw = ImageDraw.Draw(image)
    hand_path = "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf"
    try:
        title = ImageFont.truetype(hand_path, 54); body = ImageFont.truetype(hand_path, 34); small = ImageFont.truetype(hand_path, 27)
    except OSError:
        title = body = small = ImageFont.load_default()
    draw.line((95, 145, 1160, 145), fill="#2c4d72", width=4)
    draw.text((90, 70), "Northstar Logistics Co.", fill="#173b62", font=title)
    draw.text((92, 155), "Handwritten delivery invoice", fill="#5b4935", font=body)
    fields = [
        "Invoice no: NS-810", "Date: Nov 10, 2026", "PO: PO-40010",
        "Shipment: SH-8100", "Currency: USD", "Bill to: GlobalFreight Inc.",
    ]
    y = 245
    for index, line in enumerate(fields):
        draw.text((105 + (index % 2) * 560, y), line, fill="#243448", font=small)
        if index % 2: y += 72
    draw.line((90, 520, 1180, 520), fill="#8d9a9f", width=2)
    draw.text((100, 545), "1 local delivery run - SH-8100", fill="#263b4c", font=body)
    draw.text((835, 545), "$1,450.00", fill="#263b4c", font=body)
    draw.line((90, 625, 1180, 625), fill="#8d9a9f", width=2)
    draw.text((710, 675), "Subtotal", fill="#263b4c", font=small); draw.text((940, 675), "$1,450.00", fill="#263b4c", font=small)
    draw.text((710, 735), "Tax", fill="#263b4c", font=small); draw.text((990, 735), "$0.00", fill="#263b4c", font=small)
    draw.text((710, 805), "TOTAL", fill="#173b62", font=body); draw.text((925, 805), "$1,450.00", fill="#173b62", font=body)
    draw.text((105, 965), "Received in good order", fill="#6b5041", font=small)
    draw.line((105, 1040, 540, 1040), fill="#6b5041", width=2)
    draw.text((105, 1050), "driver signature", fill="#857466", font=small)
    draw.text((90, 1540), "Synthetic handwritten case-study invoice", fill="#8b8174", font=small)
    image.save(path, "PDF", resolution=150.0)


def messy_scanned_invoice(path: Path):
    page = Image.new("RGB", (1275, 1650), "#ddd8ca")
    paper = Image.new("RGB", (1120, 1480), "#f2eee1"); draw = ImageDraw.Draw(paper)
    try:
        title = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 39)
        body = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 24)
        bold = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 25)
    except OSError:
        title = body = bold = ImageFont.load_default()
    draw.rectangle((34, 32, 1080, 1425), outline="#55554f", width=2)
    draw.text((68, 68), "HARBOR COLD CHAIN LLC", fill="#303a38", font=title)
    draw.text((68, 118), "17 Freezer Port Road, Tacoma WA | Tax ID 82-4617390", fill="#5c625f", font=body)
    draw.text((760, 185), "INVOICE", fill="#3e5550", font=title)
    lines = ["Invoice: HC-920", "Date: 11/10/2026", "Due: 12/10/2026", "PO: PO-50010",
             "Shipment: SH-9200", "Currency: USD"]
    y = 215
    for line in lines: draw.text((75, y), line, fill="#343936", font=body); y += 45
    draw.rectangle((60, 530, 1055, 575), fill="#576c67")
    draw.text((76, 541), "DESCRIPTION", fill="white", font=bold); draw.text((700, 541), "QTY / RATE", fill="white", font=bold); draw.text((945, 541), "AMOUNT", fill="white", font=bold)
    draw.text((76, 610), "Refrigerated full-truckload - SH-9200", fill="#343936", font=body)
    draw.text((700, 610), "1 x $3,200", fill="#343936", font=body); draw.text((935, 610), "$3,200.00", fill="#343936", font=body)
    draw.text((720, 760), "Subtotal  $3,200.00", fill="#343936", font=bold)
    draw.text((720, 810), "Tax             $0.00", fill="#343936", font=bold)
    draw.text((720, 875), "TOTAL       $3,200.00", fill="#273d38", font=title)
    draw.ellipse((15, 850, 245, 1080), outline="#9e6b4d", width=18); draw.ellipse((42, 878, 220, 1055), outline="#b7815e", width=7)
    draw.line((555, 30, 575, 1425), fill="#c8c1b3", width=4); draw.line((565, 30, 565, 1425), fill="#faf7ec", width=2)
    draw.text((105, 1240), "FAX COPY - RECEIVED", fill="#8a4b48", font=title)
    draw.text((70, 1370), "Synthetic noisy raster scan for document-understanding tests", fill="#777269", font=body)
    paper = paper.rotate(-2.2, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="#ddd8ca")
    paper = paper.filter(ImageFilter.GaussianBlur(0.7))
    noise = Image.effect_noise(paper.size, 8).convert("RGB")
    paper = Image.blend(paper, noise, 0.055)
    page.paste(paper, ((page.width - paper.width) // 2, (page.height - paper.height) // 2))
    page.save(path, "PDF", resolution=135.0)


def atlas_copy_layout(path: Path):
    business_invoice(path, vendor="Atlas Transport LLC", address="450 Harbor Way, Newark, NJ 07114",
        tax_id="12-3454107", invoice_number="INV-504", po="PO-10045", shipment="SH-8891", currency="USD",
        description="Port-to-warehouse freight - SH-8891", quantity="1", uom="TRIP", rate="2,000.00",
        line_amount="2,000.00", subtotal="2,600.00", tax="0.00", total="2,600.00", accent="#6b3f2d",
        extra_line=("Detention - 3 billable hours - SH-8891", "3 HR", "USD 200.00", "USD 600.00"))


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    atlas_invoice(OUTPUT / "atlas-inv-504.pdf", invoice_number="INV-504", po="PO-10045")
    pacific_invoice(OUTPUT / "pacific-inv-777-no-po.pdf")
    atlas_invoice(OUTPUT / "atlas-inv-506-no-po.pdf", invoice_number="INV-506", po=None)
    atlas_invoice(OUTPUT / "atlas-investments-po-mismatch.pdf", invoice_number="INV-900", po="PO-10045", vendor="Atlas Investments LLC", tax_id="55-5559999")
    scanned_invoice(OUTPUT / "atlas-inv-504-scanned.pdf")
    atlas_invoice(OUTPUT / "atlas-inv-505-detention-overage.pdf", invoice_number="INV-505", po="PO-10055", shipment="SH-8895")
    atlas_invoice(OUTPUT / "atlas-inv-3002-partial.pdf", invoice_number="INV-3002", po="PO-30010", shipment="SH-3000",
                  base_quantity="2.5", base_rate="1,000.00", detention_hours=None)
    atlas_invoice(OUTPUT / "atlas-inv-3003-over-capacity.pdf", invoice_number="INV-3003", po="PO-30010", shipment="SH-3000",
                  base_quantity="1", base_rate="1,000.00", detention_hours=None)
    handwritten_invoice(OUTPUT / "northstar-handwritten-inv-810.pdf")
    messy_scanned_invoice(OUTPUT / "harbor-messy-scan-inv-920.pdf")
    business_invoice(OUTPUT / "summit-inv-610-currency-mismatch.pdf", vendor="Summit Air Cargo Inc.",
        address="400 Air Cargo Loop, Chicago, IL 60666", tax_id="45-8203176", invoice_number="INV-610",
        po="PO-60010", shipment="AWB-6100", currency="EUR", description="Domestic air cargo movement - AWB-6100",
        quantity="1", uom="LOAD", rate="1,800.00", line_amount="1,800.00", subtotal="1,800.00", tax="0.00", total="1,800.00")
    business_invoice(OUTPUT / "bluepeak-inv-710-rate-mismatch.pdf", vendor="BluePeak Distribution Ltd.",
        address="55 Commerce Avenue, Denver, CO 80216", tax_id="71-9305284", invoice_number="INV-710",
        po="PO-70010", shipment="SH-7100", currency="USD", description="Regional distribution route - SH-7100",
        quantity="1", uom="TRIP", rate="1,350.00", line_amount="1,350.00", subtotal="1,350.00", tax="0.00", total="1,350.00")
    business_invoice(OUTPUT / "harbor-inv-921-unsupported-storage.pdf", vendor="Harbor Cold Chain LLC",
        address="17 Freezer Port Road, Tacoma, WA 98421", tax_id="82-4617390", invoice_number="INV-921",
        po="PO-50010", shipment="SH-9200", currency="USD", description="Refrigerated full-truckload - SH-9200",
        quantity="1", uom="TRIP", rate="3,200.00", line_amount="3,200.00", subtotal="3,650.00", tax="0.00", total="3,650.00",
        extra_line=("Unscheduled cold storage - SH-9200", "3 DAY", "USD 150.00", "USD 450.00"))
    business_invoice(OUTPUT / "northstar-inv-811-arithmetic-mismatch.pdf", vendor="Northstar Logistics Co.",
        address="210 North Terminal Road, Dallas, TX 75261", tax_id="36-4918205", invoice_number="INV-811",
        po="PO-40010", shipment="SH-8100", currency="USD", description="Dedicated local delivery run - SH-8100",
        quantity="1", uom="TRIP", rate="1,450.00", line_amount="1,450.00", subtotal="1,400.00", tax="0.00", total="1,400.00")
    business_invoice(OUTPUT / "redwood-inv-990-inactive-vendor.pdf", vendor="Redwood Haulage Corp.",
        address="9 Timber Industrial Way, Portland, OR 97203", tax_id="93-6142870", invoice_number="INV-990",
        po="PO-80010", shipment="SH-9900", currency="USD", description="Heavy haul service - SH-9900",
        quantity="1", uom="TRIP", rate="2,000.00", line_amount="2,000.00", subtotal="2,000.00", tax="0.00", total="2,000.00")
    business_invoice(OUTPUT / "metroline-inv-930-missing-po.pdf", vendor="MetroLine Courier Services LLC",
        address="120 Central Dispatch Road, New York, NY 10001", tax_id="60-2847315", invoice_number="INV-930",
        po=None, shipment="SH-9300", currency="USD", description="City courier route - SH-9300",
        quantity="1", uom="ROUTE", rate="500.00", line_amount="500.00", subtotal="500.00", tax="0.00", total="500.00")
    atlas_copy_layout(OUTPUT / "atlas-inv-504-copy-layout.pdf")
    print(f"Generated 17 PDF fixtures in {OUTPUT}")


if __name__ == "__main__":
    main()
