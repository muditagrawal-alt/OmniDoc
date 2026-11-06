"""
The demo's sample library: five documents about Kestrel Analytics, a fictional company, made from
scratch so the demo needs no third-party documents and shows every feature:

    Kestrel-Annual-Report-2025.pdf     text, financial tables and a chart (answers, figures, charts)
    Kestrel-Annual-Report-2024.pdf     last year's report (Compare two versions)
    Kestrel-Northwind-Services-Agreement.pdf   a contract (Extract fields, clauses)
    Northwind-Invoice-NW-2026-0419.pdf  a scanned invoice: an image only (OCR, Extract, Privacy)
    Kestrel-Report-Summary-Hindi.pdf   a summary in Hindi (Indian languages)

    python deploy/demo/make_samples.py <folder>

Every page carries a footer saying the company is fictional.
"""
import io
import os
import sys

import fitz  # PyMuPDF

FOOTER = "Sample document for the OmniDoc demo. Kestrel Analytics and Northwind Logistics are fictional companies."
INK = (0.07, 0.09, 0.13)
MUTED = (0.33, 0.36, 0.42)
ACCENT = (0.06, 0.38, 1.0)
W, H = 595, 842  # A4 in points
MARGIN = 56


def _fonts() -> dict:
    """Body and bold faces: IBM Plex-like Helvetica built into PDF, plus a Devanagari face when one is installed."""
    deva = next((p for p in ("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
                             "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Regular.ttf",
                             "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
                             "/System/Library/Fonts/Kohinoor.ttc") if os.path.exists(p)), None)
    return {"deva": deva}


class Doc:
    """A small page writer: headings, paragraphs and tables that flow onto new pages."""

    def __init__(self, title: str):
        self.pdf = fitz.open()
        self.pdf.set_metadata({"title": title, "author": "OmniDoc sample library", "subject": FOOTER})
        self.page = None
        self.y = 0.0
        self.new_page()

    def new_page(self) -> None:
        self.page = self.pdf.new_page(width=W, height=H)
        self.page.insert_text((MARGIN, H - 30), FOOTER, fontsize=7.5, color=MUTED)
        self.page.insert_text((W - MARGIN - 30, H - 30), f"Page {self.pdf.page_count}", fontsize=7.5, color=MUTED)
        self.y = MARGIN

    def need(self, height: float) -> None:
        if self.y + height > H - 64:
            self.new_page()

    def heading(self, text: str, size: float = 16) -> None:
        self.need(size * 2.4)
        self.y += size * 0.6
        self.page.insert_text((MARGIN, self.y + size), text, fontsize=size, fontname="hebo", color=INK)
        self.y += size * 1.8

    def para(self, text: str, size: float = 10.5) -> None:
        rect = fitz.Rect(MARGIN, self.y, W - MARGIN, H - 64)
        lines = max(1, int(len(text) * size * 0.5 / (W - 2 * MARGIN)) + 1)
        self.need(lines * size * 1.5 + 8)
        rect = fitz.Rect(MARGIN, self.y, W - MARGIN, self.y + lines * size * 1.6 + 20)
        spare = self.page.insert_textbox(rect, text, fontsize=size, lineheight=1.45, color=INK)
        used = rect.height - max(0.0, spare)
        self.y += used + 8

    def table(self, header: list, rows: list, widths: list, caption: str = "") -> None:
        row_h = 18
        self.need(row_h * (len(rows) + 2) + 24)
        if caption:
            self.page.insert_text((MARGIN, self.y + 10), caption, fontsize=9.5, fontname="hebo", color=MUTED)
            self.y += 18
        x0 = MARGIN
        total = sum(widths)
        scale = (W - 2 * MARGIN) / total
        cols = [w * scale for w in widths]
        for r, row in enumerate([header] + rows):
            x = x0
            if r == 0:
                self.page.draw_rect(fitz.Rect(x0, self.y, W - MARGIN, self.y + row_h), color=None, fill=(0.94, 0.95, 0.97))
            for c, cell in enumerate(row):
                font = "hebo" if r == 0 or c == 0 and str(cell).startswith("Total") else "helv"
                text = str(cell)
                if c == 0:
                    self.page.insert_text((x + 4, self.y + 12.5), text, fontsize=9, fontname=font, color=INK)
                else:  # figures right-aligned
                    width = fitz.get_text_length(text, fontname=font, fontsize=9)
                    self.page.insert_text((x + cols[c] - width - 4, self.y + 12.5), text, fontsize=9, fontname=font, color=INK)
                x += cols[c]
            self.page.draw_line((x0, self.y + row_h), (W - MARGIN, self.y + row_h), color=(0.85, 0.87, 0.9), width=0.5)
            self.y += row_h
        # A ruled grid (outer box and column lines), the way most financial tables are printed,
        # so table detection reads it as a table and not as aligned text.
        top = self.y - row_h * (len(rows) + 1)
        grid = (0.78, 0.8, 0.85)
        self.page.draw_rect(fitz.Rect(x0, top, W - MARGIN, self.y), color=grid, width=0.6)
        x = x0
        for w in cols[:-1]:
            x += w
            self.page.draw_line((x, top), (x, self.y), color=grid, width=0.5)
        self.y += 14

    def bar_chart(self, title: str, labels: list, values: list, unit: str) -> None:
        height = 170
        self.need(height + 40)
        self.page.insert_text((MARGIN, self.y + 10), title, fontsize=9.5, fontname="hebo", color=MUTED)
        top = self.y + 24
        base = top + height - 24
        top_value = max(values) * 1.15
        width = (W - 2 * MARGIN) / len(values)
        for i, (label, value) in enumerate(zip(labels, values)):
            bar_h = (height - 40) * value / top_value
            x = MARGIN + i * width + width * 0.25
            self.page.draw_rect(fitz.Rect(x, base - bar_h, x + width * 0.5, base), color=None, fill=ACCENT)
            text = f"{value:,.0f}{unit}"
            self.page.insert_text((x, base - bar_h - 4), text, fontsize=8, color=INK)
            self.page.insert_text((x, base + 12), label, fontsize=8.5, color=MUTED)
        self.page.draw_line((MARGIN, base), (W - MARGIN, base), color=(0.7, 0.72, 0.76), width=0.6)
        self.y = base + 30

    def save(self, path: str) -> None:
        self.pdf.save(path, garbage=3, deflate=True)


def annual_report(year: int, figures: dict) -> Doc:
    f = figures
    doc = Doc(f"Kestrel Analytics Annual Report {year}")
    doc.page.insert_text((MARGIN, 120), "Kestrel Analytics Limited", fontsize=13, color=ACCENT, fontname="hebo")
    doc.page.insert_text((MARGIN, 160), f"Annual Report {year}", fontsize=30, fontname="hebo", color=INK)
    doc.page.insert_text((MARGIN, 190), f"For the financial year ended 31 March {year}", fontsize=11, color=MUTED)
    doc.y = 240
    doc.para(f"Kestrel Analytics builds demand-forecasting software for retailers and logistics companies in India, "
             f"South-East Asia and the Middle East. In financial year {year} revenue was INR {f['revenue']:,} crore, "
             f"{f['growth']}% more than the year before, and operating margin was {f['margin']}%.")
    doc.heading("Letter from the chief executive", 14)
    doc.para(f"Dear shareholders, this was a year of {f['tone']}. Subscription revenue grew {f['subs_growth']}% as "
             f"{f['customers']:,} customers renewed or expanded, and our largest new contract, with Northwind "
             f"Logistics, began in the fourth quarter. We hired {f['hires']} engineers in Pune and Bengaluru and "
             f"opened an office in Dubai. {f['ceo_extra']}")
    doc.para("We remain cautious about the year ahead. Freight costs and currency movements affect our customers, "
             "and new data-protection rules under India's Digital Personal Data Protection Act change how we store "
             "personal data. Priya Raman, Chief Executive Officer.")
    doc.heading("Financial highlights", 14)
    doc.table(["INR crore", f"FY{year}", f"FY{year - 1}", "Change"], [
        ["Revenue", f"{f['revenue']:,}", f"{f['revenue_prev']:,}", f"{f['growth']}%"],
        ["Subscription revenue", f"{f['subs']:,}", f"{f['subs_prev']:,}", f"{f['subs_growth']}%"],
        ["Services revenue", f"{f['revenue'] - f['subs']:,}", f"{f['revenue_prev'] - f['subs_prev']:,}",
         f"{round(((f['revenue'] - f['subs']) / (f['revenue_prev'] - f['subs_prev']) - 1) * 100, 1)}%"],
        ["Operating profit", f"{f['op_profit']:,}", f"{f['op_profit_prev']:,}",
         f"{round((f['op_profit'] / f['op_profit_prev'] - 1) * 100, 1)}%"],
        ["Net profit", f"{f['net']:,}", f"{f['net_prev']:,}", f"{round((f['net'] / f['net_prev'] - 1) * 100, 1)}%"],
    ], [3, 1.4, 1.4, 1.2], caption="Table 1. Financial highlights")
    doc.bar_chart("Figure 1. Revenue by region, INR crore", f["regions"], f["region_values"], "")
    doc.heading("Statement of profit and loss", 14)
    doc.table(["INR crore", f"FY{year}", f"FY{year - 1}"], [
        ["Revenue from operations", f"{f['revenue']:,}", f"{f['revenue_prev']:,}"],
        ["Employee costs", f"{f['staff']:,}", f"{f['staff_prev']:,}"],
        ["Cloud and data costs", f"{f['cloud']:,}", f"{f['cloud_prev']:,}"],
        ["Other expenses", f"{f['revenue'] - f['staff'] - f['cloud'] - f['op_profit']:,}",
         f"{f['revenue_prev'] - f['staff_prev'] - f['cloud_prev'] - f['op_profit_prev']:,}"],
        ["Operating profit", f"{f['op_profit']:,}", f"{f['op_profit_prev']:,}"],
        ["Tax", f"{f['op_profit'] - f['net']:,}", f"{f['op_profit_prev'] - f['net_prev']:,}"],
        ["Total net profit", f"{f['net']:,}", f"{f['net_prev']:,}"],
    ], [3, 1.4, 1.4], caption="Table 2. Statement of profit and loss for the year ended 31 March")
    doc.heading("Balance sheet", 14)
    doc.table(["INR crore", f"31 Mar {year}", f"31 Mar {year - 1}"], [
        ["Cash and equivalents", f"{f['cash']:,}", f"{f['cash_prev']:,}"],
        ["Trade receivables", f"{f['receivables']:,}", f"{f['receivables_prev']:,}"],
        ["Total assets", f"{f['assets']:,}", f"{f['assets_prev']:,}"],
        ["Borrowings", f"{f['debt']:,}", f"{f['debt_prev']:,}"],
        ["Total equity", f"{f['equity']:,}", f"{f['equity_prev']:,}"],
    ], [3, 1.4, 1.4], caption="Table 3. Balance sheet")
    doc.heading("Principal risks", 14)
    for risk in f["risks"]:
        doc.para("- " + risk)  # the built-in PDF font has no bullet glyph
    doc.heading("Outlook", 14)
    doc.para(f["outlook"])
    return doc


FY2025 = dict(
    revenue=1284, revenue_prev=1102, growth=16.5, margin=18.4, subs=962, subs_prev=801, subs_growth=20.1,
    customers=1840, hires=210, tone="steady growth and one difficult quarter",
    ceo_extra="The third quarter was weaker than planned after two retail customers delayed renewals; both renewed in March.",
    op_profit=236, op_profit_prev=187, net=171, net_prev=138, staff=598, staff_prev=531, cloud=171, cloud_prev=158,
    cash=412, cash_prev=356, receivables=228, receivables_prev=214, assets=1530, assets_prev=1338,
    debt=95, debt_prev=140, equity=1012, equity_prev=861,
    regions=["India", "South-East Asia", "Middle East", "Europe"], region_values=[702, 318, 186, 78],
    risks=["Customer concentration: the ten largest customers provide 31% of revenue (FY2024: 34%).",
           "Currency: 38% of revenue is billed in US dollars and UAE dirhams.",
           "Data protection: the DPDP Act requires consent records and Indian storage for some customer data.",
           "Cloud costs: a 10% rise in cloud prices would reduce operating margin by about 1.3 points."],
    outlook="For FY2026 we expect revenue growth of 14% to 17% and an operating margin of 18% to 19%, "
            "assuming the Northwind Logistics contract ramps up as planned.",
)
FY2024 = dict(
    revenue=1102, revenue_prev=964, growth=14.3, margin=17.0, subs=801, subs_prev=668, subs_growth=19.9,
    customers=1610, hires=180, tone="expansion",
    ceo_extra="We entered the Middle East through partners and signed our first customers in Riyadh and Dubai.",
    op_profit=187, op_profit_prev=149, net=138, net_prev=109, staff=531, staff_prev=478, cloud=158, cloud_prev=139,
    cash=356, cash_prev=301, receivables=214, receivables_prev=190, assets=1338, assets_prev=1182,
    debt=140, debt_prev=162, equity=861, equity_prev=745,
    regions=["India", "South-East Asia", "Middle East", "Europe"], region_values=[628, 287, 112, 75],
    risks=["Customer concentration: the ten largest customers provide 34% of revenue.",
           "Currency: 35% of revenue is billed in US dollars and UAE dirhams.",
           "Hiring: competition for machine-learning engineers in Bengaluru raised salaries by 12%."],
    outlook="For FY2025 we expect revenue growth of 13% to 16% and an operating margin of about 17.5%.",
)


def agreement() -> Doc:
    doc = Doc("Master Services Agreement between Kestrel Analytics and Northwind Logistics")
    doc.heading("Master Services Agreement", 20)
    doc.para("This agreement is made on 14 January 2025 between Kestrel Analytics Limited, Pune, Maharashtra "
             "(\"Kestrel\") and Northwind Logistics Private Limited, Mumbai, Maharashtra (\"Northwind\").")
    clauses = [
        ("1. Services", "Kestrel will provide its demand-forecasting platform to Northwind for 42 warehouses, with "
         "implementation support during the first 90 days."),
        ("2. Term", "The agreement starts on 1 February 2025 and runs for three years. It renews for one year at a "
         "time unless either party gives 90 days' written notice."),
        ("3. Fees", "Northwind will pay a subscription fee of INR 2,40,00,000 per year, invoiced quarterly in advance, "
         "and implementation fees of INR 36,00,000 in total."),
        ("4. Payment terms", "Invoices are payable within 30 days. Late payments carry interest at 1% per month."),
        ("5. Service levels", "Kestrel will keep the platform available 99.5% of each month. If availability falls "
         "below that, Northwind receives a credit of 5% of that month's fee for each 0.5 point below."),
        ("6. Data protection", "Kestrel processes personal data only on Northwind's instructions, stores it in India, "
         "and deletes it within 60 days after the agreement ends."),
        ("7. Limitation of liability", "Each party's total liability is capped at the fees paid in the twelve months "
         "before the claim, except for breaches of confidentiality or data protection."),
        ("8. Termination", "Either party may end the agreement if the other commits a material breach and does not "
         "fix it within 30 days of written notice."),
        ("9. Governing law", "This agreement is governed by the laws of India. The courts of Mumbai have exclusive "
         "jurisdiction."),
    ]
    for title, text in clauses:
        doc.heading(title, 12)
        doc.para(text)
    doc.heading("Signed", 12)
    doc.para("For Kestrel Analytics Limited: Priya Raman, Chief Executive Officer, 14 January 2025.")
    doc.para("For Northwind Logistics Private Limited: Arjun Mehta, Director, 14 January 2025.")
    return doc


def invoice_scan(path: str) -> None:
    """An invoice rendered, then turned into a slightly rotated grey image: a scan with no text layer."""
    from PIL import Image, ImageFilter
    doc = Doc("Invoice NW-2026-0419")
    doc.page.insert_text((MARGIN, 100), "TAX INVOICE", fontsize=22, fontname="hebo", color=INK)
    doc.y = 130
    for line in ["Northwind Logistics Private Limited", "Plot 12, Andheri East, Mumbai 400069",
                 "GSTIN: 27AACCN4482K1Z3", "", "Bill to: Kestrel Analytics Limited, Pune 411014",
                 "Invoice No: NW-2026-0419", "Invoice Date: 12 August 2026", "Due Date: 11 September 2026"]:
        doc.page.insert_text((MARGIN, doc.y), line, fontsize=11, color=INK)
        doc.y += 18
    doc.y += 10
    doc.table(["Description", "Qty", "Rate (INR)", "Amount (INR)"], [
        ["Freight and handling, July 2026", "1", "6,00,000", "6,00,000"],
        ["Warehouse storage, 120 pallets", "1", "1,80,000", "1,80,000"],
        ["Customs clearance", "8", "7,500", "60,000"],
        ["IGST 18% on 8,40,000", "", "", "1,51,200"],
        ["Total Due", "", "", "9,91,200"],
    ], [3.2, 0.8, 1.2, 1.4])
    doc.para("Payment within 30 days to HDFC Bank, IFSC HDFC0001234, account 50200012345678.")
    pix = doc.pdf[0].get_pixmap(dpi=150, colorspace=fitz.csGRAY)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).rotate(-0.8, expand=False, fillcolor=255).filter(ImageFilter.SMOOTH)
    out = fitz.open()
    page = out.new_page(width=W, height=H)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    page.insert_image(page.rect, stream=buf.getvalue())
    out.set_metadata({"title": "Invoice NW-2026-0419 (scan)", "subject": FOOTER})
    out.save(path, garbage=3, deflate=True)


def hindi_summary(path: str, font: str) -> bool:
    if not font:
        return False
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.insert_font(fontname="deva", fontfile=font)
    text = ("केस्ट्रेल एनालिटिक्स: वार्षिक रिपोर्ट 2025 का सारांश\n\n"
            "वित्त वर्ष 2025 में कंपनी का राजस्व 1,284 करोड़ रुपये रहा, जो पिछले वर्ष से 16.5 प्रतिशत अधिक है। "
            "परिचालन मार्जिन 18.4 प्रतिशत रहा और शुद्ध लाभ 171 करोड़ रुपये हुआ।\n\n"
            "भारत से 702 करोड़ रुपये का राजस्व आया, दक्षिण-पूर्व एशिया से 318 करोड़ और मध्य पूर्व से 186 करोड़। "
            "कंपनी ने पुणे और बेंगलुरु में 210 इंजीनियरों की भर्ती की।\n\n"
            "मुख्य जोखिम: बड़े ग्राहकों पर निर्भरता, मुद्रा में उतार-चढ़ाव और डेटा संरक्षण के नए नियम। "
            "वित्त वर्ष 2026 में राजस्व 14 से 17 प्रतिशत बढ़ने की उम्मीद है।")
    page.insert_textbox(fitz.Rect(MARGIN, MARGIN, W - MARGIN, H - 80), text, fontsize=12, fontname="deva", lineheight=1.6)
    page.insert_text((MARGIN, H - 30), FOOTER, fontsize=7.5, color=MUTED)
    pdf.set_metadata({"title": "Kestrel Analytics Annual Report 2025, summary in Hindi", "subject": FOOTER})
    pdf.save(path, garbage=3, deflate=True)
    return True


def main(folder: str) -> None:
    os.makedirs(folder, exist_ok=True)
    annual_report(2025, FY2025).save(os.path.join(folder, "Kestrel-Annual-Report-2025.pdf"))
    annual_report(2024, FY2024).save(os.path.join(folder, "Kestrel-Annual-Report-2024.pdf"))
    agreement().save(os.path.join(folder, "Kestrel-Northwind-Services-Agreement.pdf"))
    invoice_scan(os.path.join(folder, "Northwind-Invoice-NW-2026-0419.pdf"))
    made_hindi = hindi_summary(os.path.join(folder, "Kestrel-Report-Summary-Hindi.pdf"), _fonts()["deva"])
    print(f"Sample library written to {folder}" + ("" if made_hindi else " (no Devanagari font: Hindi summary skipped)"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo-library")
