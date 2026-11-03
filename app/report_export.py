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

from .logo_presentation import prepare_company_logo


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
    historical_vacations: list[dict[str, Any]] | None = None,
    historical_vacation_count: int = 0,
    historical_notices: list[dict[str, Any]] | None = None,
    historical_notice_count: int = 0,
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
    logo_bytes = prepare_company_logo(
        getattr(branding, "logo_bytes", None) if branding else None,
        fit=getattr(branding, "logo_fit", "contain") if branding else "contain",
        scale=getattr(branding, "logo_scale", 100) if branding else 100,
        alignment=getattr(branding, "logo_alignment", "center") if branding else "center",
        background=getattr(branding, "logo_background", "white") if branding else "white",
    )
    if logo_bytes:
        logo_stream = io.BytesIO(logo_bytes)
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

    if historical_vacation_count:
        story.append(Paragraph("Antecedentes de vacaciones importados (LSVAC)", h2))
        story.append(Paragraph(
            f"{historical_vacation_count} movimientos vinculados al legajo. "
            "No constituyen saldo vigente, aprobación de vacaciones ni constancia de pago. "
            "Requieren conciliación profesional con los registros operativos.",
            small,
        ))
        history_rows = [["Período original", "Desde", "Hasta", "Días", "Importe origen"]]
        for row in (historical_vacations or [])[:12]:
            source = row.get("source") or {}
            history_rows.append([
                escape(f"{source.get('period_from') or '—'} / {source.get('period_to') or '—'}"),
                escape(str(source.get("vacation_start") or "—")),
                escape(str(source.get("vacation_end") or "—")),
                escape(str(source.get("days") if source.get("days") is not None else "—")),
                escape(str(source.get("vacation_amount") if source.get("vacation_amount") is not None else "—")),
            ])
        if len(history_rows) > 1:
            history_table = Table(history_rows, colWidths=[49 * mm, 33 * mm, 33 * mm, 21 * mm, 40 * mm], repeatRows=1)
            history_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5EDFA")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#DCE4EF")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(history_table)
        if historical_vacation_count > len(historical_vacations or []):
            story.append(Paragraph(
                "Se muestra una muestra de movimientos. El historial íntegro se consulta "
                "en el módulo Vacaciones y se puede exportar a CSV.", small
            ))

    if historical_notice_count:
        story.append(Paragraph("Preavisos históricos importados (LSPRE)", h2))
        story.append(Paragraph(
            f"{historical_notice_count} antecedentes vinculados, sin confirmación de "
            "notificación, cumplimiento, fecha efectiva de egreso ni pago de indemnización. "
            "Los días en origen no reemplazan la escala legal vigente.",
            small,
        ))
        rows = [["FECPRE", "FECSAL", "FECSA1", "DIAPRE", "Marcador"]]
        for row in (historical_notices or [])[:12]:
            info = row.get("source") or {}
            rows.append([
                escape(str(info.get("notice_date_source") or "—")),
                escape(str(info.get("departure_date_source") or "—")),
                escape(str(info.get("secondary_date_source") or "—")),
                escape(str(info.get("days") if info.get("days") is not None else "—")),
                "BORRAD=S" if info.get("deleted_source") else "Sin marca",
            ])
        if len(rows) > 1:
            table = Table(rows, colWidths=[37 * mm, 37 * mm, 37 * mm, 28 * mm, 37 * mm], repeatRows=1)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5EDFA")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#DCE4EF")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(table)
        if historical_notice_count > len(historical_notices or []):
            story.append(Paragraph(
                "Se incluye una muestra; el histórico completo LSPRE se puede "
                "consultar y exportar desde el módulo de preavisos históricos.", small,
            ))

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
