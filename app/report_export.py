from __future__ import annotations

import io
from datetime import date, datetime
from html import escape
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _gs(value: Any) -> str:
    return f"{int(value or 0):,}".replace(",", ".")


def _date(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    return str(value or "—")


def build_employee_report_pdf(
    *,
    company: Any,
    employee: Any,
    calculations: list[Any],
    certificates: list[Any],
    vacations: list[Any],
    aguinaldos: list[Any],
    branding: Any | None = None,
) -> bytes:
    stream = io.BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm, topMargin=15 * mm, bottomMargin=16 * mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("TitleDL", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=18, leading=21, textColor=colors.HexColor("#173B86"))
    h2 = ParagraphStyle("H2DL", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=colors.HexColor("#0B1F48"), spaceBefore=10, spaceAfter=7)
    small = ParagraphStyle("SmallDL", parent=styles["Normal"], fontSize=8, leading=10, textColor=colors.HexColor("#66758D"))
    normal = ParagraphStyle("NormalDL", parent=styles["Normal"], fontSize=9, leading=12)
    right = ParagraphStyle("RightDL", parent=small, alignment=TA_RIGHT)

    primary = getattr(branding, "primary_color", "#173B86") or "#173B86"
    header_cells: list[Any] = []
    if branding and getattr(branding, "logo_bytes", None):
        logo_stream = io.BytesIO(branding.logo_bytes)
        header_cells.append(Image(logo_stream, width=22 * mm, height=22 * mm, kind="proportional"))
    else:
        header_cells.append(Paragraph("<b>DL</b>", ParagraphStyle("DL", parent=styles["Normal"], fontSize=18, textColor=colors.white, alignment=TA_CENTER)))
    details = [f"<b>{escape(company.legal_name)}</b>", f"RUC {escape(company.ruc)}"]
    if company.address:
        details.append(escape(company.address))
    header_cells.append(Paragraph("<br/>".join(details), normal))
    header = Table([header_cells], colWidths=[28 * mm, 148 * mm])
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor(primary)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(primary)),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#DDE5F0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story: list[Any] = [header, Spacer(1, 8 * mm), Paragraph("INFORME INTEGRAL DEL FUNCIONARIO", title), Paragraph(f"Generado el {_date(date.today())}", right), Spacer(1, 4 * mm)]

    data = [
        ["Funcionario", employee.full_name, "Cédula", employee.document_number],
        ["Cargo", employee.position or "—", "Ingreso", _date(employee.admission_date)],
        ["Salario base", f"Gs. {_gs(employee.base_salary)}", "Estado", employee.status],
        ["Contrato", employee.contract_type, "IPS", "Sí" if employee.ips_contributor else "No"],
    ]
    table = Table(data, colWidths=[30 * mm, 58 * mm, 28 * mm, 60 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF4FF")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#EEF4FF")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#DCE4EF")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([table, Paragraph("Cálculos guardados", h2)])
    calc_rows = [["Fecha", "Tipo", "Periodo", "Monto", "Estado"]]
    for item in calculations:
        calc_rows.append([_date(item.created_at), item.calculation_type, item.reference_period or "—", f"Gs. {_gs(item.amount)}", item.status])
    if len(calc_rows) == 1:
        calc_rows.append(["—", "Sin cálculos", "—", "—", "—"])
    calc_table = Table(calc_rows, colWidths=[29 * mm, 42 * mm, 32 * mm, 38 * mm, 30 * mm], repeatRows=1)
    calc_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(primary)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.7),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#DCE4EF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(calc_table)

    story.append(Paragraph("Vacaciones y aguinaldo", h2))
    vac_text = ", ".join(f"{v.period_year}: {v.used_days}/{v.entitled_days} días ({v.status})" for v in vacations) or "Sin registros de vacaciones."
    ag_text = ", ".join(f"{a.year}: Gs. {_gs(a.calculated_amount)} ({a.status})" for a in aguinaldos) or "Sin registros de aguinaldo."
    story.extend([Paragraph(escape(vac_text), normal), Paragraph(escape(ag_text), normal)])

    story.append(Paragraph("Documentos generados", h2))
    cert_rows = [["Fecha", "Documento", "Estado", "Creado por"]]
    for item in certificates:
        cert_rows.append([_date(item.issue_date), item.title, item.status, item.created_by])
    if len(cert_rows) == 1:
        cert_rows.append(["—", "Sin documentos generados", "—", "—"])
    cert_table = Table(cert_rows, colWidths=[28 * mm, 75 * mm, 28 * mm, 46 * mm], repeatRows=1)
    cert_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B1F48")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.7),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#DCE4EF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(cert_table)

    footer_text = getattr(branding, "document_footer", "Generado por Digit Laboral") if branding else "Generado por Digit Laboral"
    story.extend([Spacer(1, 8 * mm), Paragraph(escape(footer_text), ParagraphStyle("Foot", parent=small, alignment=TA_CENTER))])
    doc.build(story)
    return stream.getvalue()
