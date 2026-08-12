"""
Billing invoice export — PDF (reportlab) and Excel (openpyxl), both already
project dependencies (see catalogue_render_service.py's PDF use and
requirements.txt). Reads directly off a persisted Sale row (the immutable
snapshot) plus the tenant's own branding fields (name/GST/logo/contact) —
never recomputed, never touches the live gold rate.
"""

import io
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from openpyxl import Workbook

from app.models.billing import Sale
from app.models.auth import Tenant


def _rows(sale: Sale):
    return [
        ("Gold Value", sale.gold_value_amount),
        (f"Making Charge ({sale.making_charge_type})", sale.making_charge_amount),
        (f"Wastage ({sale.wastage_type})", sale.wastage_amount),
        ("Stone Charge", sale.stone_charge_amount),
        ("Other Charges", sale.other_charges_amount),
        ("Subtotal", sale.subtotal_before_tax),
        (f"Tax / GST ({sale.tax_rate_percent}%)", sale.tax_amount),
        ("Discount", -sale.discount_amount),
        ("Final Amount", sale.final_amount),
    ]


def build_invoice_pdf(sale: Sale, tenant: Optional[Tenant]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - 25 * mm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, (tenant.name if tenant else "Invoice"))
    c.setFont("Helvetica", 9)
    y -= 6 * mm
    if tenant and tenant.gst_number:
        c.drawString(20 * mm, y, f"GSTIN: {tenant.gst_number}")
        y -= 5 * mm
    if tenant and tenant.contact_phone:
        c.drawString(20 * mm, y, f"Phone: {tenant.contact_phone}")
        y -= 5 * mm

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(20 * mm, y, f"Invoice: {sale.invoice_number}")
    c.drawRightString(width - 20 * mm, y, sale.sale_timestamp.strftime("%d-%b-%Y %H:%M"))
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, f"Customer: {sale.customer_name or sale.customer_id or 'Walk-in'}")
    if sale.customer_phone:
        c.drawRightString(width - 20 * mm, y, sale.customer_phone)
    y -= 8 * mm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, f"{sale.product_code} — {sale.product_name}")
    y -= 5 * mm
    c.setFont("Helvetica", 9)
    huid = f" · HUID {sale.huid}" if sale.huid else ""
    vendor = f" · Vendor {sale.vendor_name}" if sale.vendor_name else ""
    c.drawString(
        20 * mm, y,
        f"Purity {sale.purity} · Gross {sale.gross_weight_grams}g · Net {sale.net_gold_weight_grams}g{huid}{vendor}",
    )
    y -= 5 * mm
    c.drawString(20 * mm, y, f"Gold Rate Applied: Rs.{sale.gold_rate_applied:.2f}/g ({sale.gold_rate_source})")
    y -= 10 * mm

    c.line(20 * mm, y, width - 20 * mm, y)
    y -= 8 * mm
    c.setFont("Helvetica", 10)
    for label, value in _rows(sale):
        c.drawString(20 * mm, y, label)
        c.drawRightString(width - 20 * mm, y, f"Rs.{value:,.2f}")
        y -= 6 * mm

    y -= 4 * mm
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, y, f"Payment: {sale.payment_method} ({sale.payment_status})")
    y -= 15 * mm
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(20 * mm, y, "This is a system-generated invoice.")

    c.showPage()
    c.save()
    return buf.getvalue()


def build_invoice_excel(sale: Sale, tenant: Optional[Tenant]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Invoice"

    header = [
        ("Business", tenant.name if tenant else ""),
        ("GSTIN", tenant.gst_number if tenant else ""),
        ("Invoice No", sale.invoice_number),
        ("Date", sale.sale_timestamp.strftime("%d-%b-%Y %H:%M")),
        ("Customer", sale.customer_name or sale.customer_id or "Walk-in"),
        ("Phone", sale.customer_phone or ""),
        ("Product Code", sale.product_code),
        ("Product", sale.product_name),
        ("Vendor", sale.vendor_name or ""),
        ("HUID", sale.huid or ""),
        ("Purity", sale.purity),
        ("Gross Weight (g)", sale.gross_weight_grams),
        ("Net Gold Weight (g)", sale.net_gold_weight_grams),
        ("Gold Rate Applied (Rs/g)", sale.gold_rate_applied),
        ("Gold Rate Source", sale.gold_rate_source),
    ]
    for row in header:
        ws.append(row)

    ws.append([])
    ws.append(["Charge", "Amount (Rs)"])
    for label, value in _rows(sale):
        ws.append([label, value])
    ws.append([])
    ws.append(["Payment Method", sale.payment_method])
    ws.append(["Payment Status", sale.payment_status])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
