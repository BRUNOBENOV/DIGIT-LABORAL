from __future__ import annotations

import json
from calendar import monthrange
from datetime import date, datetime
from io import BytesIO
from html import escape
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from .form_utils import clean_text
from .models import AuditLog, CalculationRecord, Company, CompanyBranding, Employee


SALARY_CALCULATION_TYPES = ("salary", "suite_salary")


def _dict_json(raw: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _whole_amount(value: Any, fallback: int = 0) -> int:
    try:
        # Values are Guaranies, stored as integer units in DIGIT-LABORAL.
        from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
        parsed = Decimal(str(value if value not in (None, "") else fallback))
        if not parsed.is_finite():
            return fallback
        return int(parsed.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (ValueError, TypeError, ArithmeticError):
        return fallback


def _amount_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for row in value[:100]:
        if not isinstance(row, dict):
            continue
        rows.append({
            "label": clean_text(str(row.get("label") or "Concepto laboral"), max_length=160),
            "amount": max(0, _whole_amount(row.get("amount"))),
            "formula": clean_text(str(row.get("formula") or ""), max_length=240),
            "legal": clean_text(str(row.get("legal") or ""), max_length=160),
        })
    return rows


def build_salary_report_model(
    db: Session, item: CalculationRecord, company: Company, employee: Employee
) -> dict[str, Any]:
    """Present the immutable saved calculation; this function never recalculates salary."""
    inputs = _dict_json(item.input_json)
    saved = _dict_json(item.result_json)
    identity = saved.get("identity") if isinstance(saved.get("identity"), dict) else {}
    period = clean_text(str(item.reference_period or saved.get("period") or inputs.get("month") or ""), max_length=20)
    period_start = period_end = None
    period_display = period or "Periodo no registrado"
    if len(period) == 7 and period[4] == "-":
        try:
            period_start = date.fromisoformat(period + "-01")
            period_end = date(period_start.year, period_start.month, monthrange(period_start.year, period_start.month)[1])
            period_display = period_start.strftime("%m/%Y")
        except ValueError:
            period_start = period_end = None

    has_itemized_rows = isinstance(saved.get("earnings"), list) and isinstance(saved.get("deductions"), list)
    if has_itemized_rows:
        earnings = _amount_rows(saved.get("earnings"))
        deductions = _amount_rows(saved.get("deductions"))
        gross = max(0, _whole_amount(saved.get("gross"), sum(row["amount"] for row in earnings)))
        discounts = max(0, _whole_amount(saved.get("discounts"), sum(row["amount"] for row in deductions)))
        net = _whole_amount(saved.get("net"), item.amount)
    else:
        # Compatibility for older calculations, whose result JSON contains totals rather than concept arrays.
        gross_input = max(0, _whole_amount(inputs.get("gross")))
        other_income = max(0, _whole_amount(inputs.get("other_income")))
        ips = max(0, _whole_amount(saved.get("ips_employee")))
        other_discount = max(0, _whole_amount(inputs.get("other_discount")))
        earnings = [
            {"label": "Haberes brutos del período", "amount": gross_input, "formula": "", "legal": ""},
            {"label": "Otros ingresos registrados", "amount": other_income, "formula": "", "legal": ""},
        ]
        deductions = [
            {"label": "Aporte IPS del trabajador", "amount": ips, "formula": "", "legal": ""},
            {"label": "Otros descuentos registrados", "amount": other_discount, "formula": "", "legal": ""},
        ]
        gross = max(0, _whole_amount(saved.get("gross_computable"), gross_input + other_income))
        discounts = max(0, _whole_amount(saved.get("discounts"), ips + other_discount))
        net = _whole_amount(saved.get("net"), item.amount)

    warnings: list[str] = []
    source_warnings = saved.get("warnings", [])
    if isinstance(source_warnings, list):
        warnings.extend(clean_text(str(value), max_length=350) for value in source_warnings if value and str(value).strip())

    employer_name = clean_text(str(identity.get("employer") or inputs.get("employer") or company.legal_name or ""), max_length=220)
    employer_ruc = clean_text(str(identity.get("ruc") or inputs.get("ruc") or company.ruc or ""), max_length=60)
    employee_name = clean_text(str(identity.get("employee") or inputs.get("employee") or employee.full_name or ""), max_length=220)
    employee_ci = clean_text(str(identity.get("ci") or inputs.get("ci") or employee.document_number or ""), max_length=60)
    position = clean_text(str(identity.get("position") or inputs.get("position") or employee.position or ""), max_length=160)

    if not period_start:
        warnings.append("El período no tiene formato AAAA-MM válido. Revisá el cálculo de origen antes de utilizar este documento como recibo.")
    if not employer_name or not employer_ruc:
        warnings.append("Falta el nombre patronal o el RUC en el cálculo y en el legajo.")
    if not employee_name or not employee_ci:
        warnings.append("Falta la identidad documental del funcionario en el cálculo y en el legajo.")
    if not earnings:
        warnings.append("El cálculo guardado no tiene conceptos de haberes para mostrar.")
    if not deductions:
        warnings.append("El cálculo guardado no tiene conceptos de descuentos para mostrar.")
    if sum(row["amount"] for row in earnings) != gross:
        warnings.append("La suma de conceptos de haberes no coincide con el total bruto guardado. Se muestra el total persistido sin recalcularlo.")
    if sum(row["amount"] for row in deductions) != discounts:
        warnings.append("La suma de conceptos de descuentos no coincide con el total guardado. Se muestra el total persistido sin recalcularlo.")
    if gross - discounts != net:
        warnings.append("El bruto menos los descuentos no coincide con el neto persistido. Revisá el cálculo de origen; no se alteraron los importes.")
    if item.status == "Anulado":
        warnings.append("Este cálculo está anulado. Solo se permite consultar su historial; no se puede volver a imprimir.")

    branding = db.scalar(select(CompanyBranding).where(CompanyBranding.company_id == company.id))
    issued_date = clean_text(str(saved.get("issued_date") or ""), max_length=40)
    if not issued_date and item.created_at:
        issued_date = item.created_at.strftime("%d/%m/%Y")
    representative = clean_text(str(company.legal_representative or (branding.signature_name if branding else "") or company.responsible_name or ""), max_length=180)
    payment_method = clean_text(str(identity.get("payment_method") or inputs.get("payment_method") or "No registrado"), max_length=80)

    return {
        "code": f"DL-LS-{item.id:06d}",
        "record_id": item.id,
        "period": period,
        "period_display": period_display,
        "period_start": period_start,
        "period_end": period_end,
        "issued_date": issued_date or "No registrada",
        "employer_name": employer_name,
        "employer_ruc": employer_ruc,
        "employer_address": company.address or "",
        "employer_city": company.city or "",
        "employer_phone": company.phone or "",
        "ips_employer_number": company.ips_employer_number or "",
        "mtess_employer_number": company.mtess_employer_number or "",
        "representative": representative,
        "employee_name": employee_name,
        "employee_ci": employee_ci,
        "employee_code": employee.employee_code or "",
        "employee_position": position,
        "admission_date": employee.admission_date,
        "payment_method": payment_method,
        "earnings": earnings,
        "deductions": deductions,
        "gross": gross,
        "discounts": discounts,
        "net": net,
        "notes": clean_text(str(item.notes or inputs.get("notes") or ""), max_length=600),
        "warnings": list(dict.fromkeys(warnings)),
        "status": item.status or "Sin estado",
        "created_at": item.created_at,
        "created_by": item.created_by or "",
        "calculation_type": item.calculation_type,
        "source": item.source or "",
        "company_id": company.id,
        "employee_id": employee.id,
        "can_reprint": item.status != "Anulado",
        "partial": bool(saved.get("partial", False)),
    }


def salary_report_history(db: Session, item: CalculationRecord) -> list[dict[str, Any]]:
    """Previous saved calculations for the same employee/company/month, oldest to newest."""
    query = select(CalculationRecord).where(
        CalculationRecord.company_id == item.company_id,
        CalculationRecord.employee_id == item.employee_id,
        CalculationRecord.calculation_type.in_(SALARY_CALCULATION_TYPES),
        CalculationRecord.reference_period == item.reference_period,
    ).order_by(CalculationRecord.created_at.asc(), CalculationRecord.id.asc())
    records = list(db.scalars(query.limit(100)))
    if item.id not in {record.id for record in records}:
        records.append(item)
        records.sort(key=lambda record: (record.created_at or datetime.min, record.id))
    return [
        {
            "id": record.id,
            "version": index,
            "current": record.id == item.id,
            "created_at": record.created_at,
            "amount": record.amount,
            "status": record.status,
            "calculation_type": "Motor profesional" if record.calculation_type == "suite_salary" else "Cálculo clásico",
        }
        for index, record in enumerate(records, start=1)
    ]


def build_salary_report_pdf(model: dict[str, Any]) -> bytes:
    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=20 * mm, title="Liquidación de salarios",
        author="Digit Laboral",
    )
    styles = getSampleStyleSheet()
    navy = colors.HexColor("#05256d")
    pale = colors.HexColor("#eef3fb")
    muted = colors.HexColor("#52627a")
    body = ParagraphStyle("ReceiptBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.5, leading=12, textColor=colors.HexColor("#17243a"))
    small = ParagraphStyle("ReceiptSmall", parent=body, fontSize=7.3, leading=10, textColor=muted)
    heading = ParagraphStyle("ReceiptHeading", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=navy, spaceAfter=3)
    subheading = ParagraphStyle("ReceiptSubheading", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=9.5, leading=12, textColor=navy, spaceBefore=7, spaceAfter=5)
    centered = ParagraphStyle("ReceiptCenter", parent=body, alignment=TA_CENTER)
    amount_style = ParagraphStyle("ReceiptAmount", parent=body, alignment=TA_RIGHT, fontName="Helvetica-Bold")
    header_style = ParagraphStyle("ReceiptTableHeader", parent=small, textColor=colors.white, fontName="Helvetica-Bold")

    def p(value: Any, style=body):
        return Paragraph(escape(str(value or "")).replace("\n", "<br/>"), style)

    def gs(value: Any) -> str:
        return "Gs. " + f"{_whole_amount(value):,}".replace(",", ".")

    story = [
        p("DIGIT-LABORAL · DOCUMENTO INTERNO", small),
        Spacer(1, 3 * mm),
        p("LIQUIDACIÓN DE SALARIOS", heading),
        p(f"Referencia: {model['code']} · Estado del cálculo: {model['status']}", small),
        Spacer(1, 4 * mm),
    ]
    company_rows = [
        [p("EMPLEADOR", small), p(model["employer_name"]), p("RUC", small), p(model["employer_ruc"])],
        [p("N.º patronal IPS", small), p(model["ips_employer_number"] or "No registrado"), p("MTESS", small), p(model["mtess_employer_number"] or "No registrado")],
        [p("Dirección", small), p(model["employer_address"] or "No registrada"), p("Ciudad", small), p(model["employer_city"] or "No registrada")],
    ]
    company_table = Table(company_rows, colWidths=[25*mm, 63*mm, 18*mm, 58*mm])
    company_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), pale), ("BOX",(0,0),(-1,-1),0.5,colors.HexColor("#d5deea")),
        ("INNERGRID",(0,0),(-1,-1),0.35,colors.HexColor("#d5deea")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("LEFTPADDING",(0,0),(-1,-1),6),
        ("RIGHTPADDING",(0,0),(-1,-1),6), ("TOPPADDING",(0,0),(-1,-1),6), ("BOTTOMPADDING",(0,0),(-1,-1),6),
    ]))
    story.extend([p("DATOS DEL EMPLEADOR", subheading), company_table, Spacer(1, 3*mm)])
    employee_rows = [
        [p("FUNCIONARIO", small), p(model["employee_name"]), p("Cédula", small), p(model["employee_ci"])],
        [p("Código", small), p(model["employee_code"] or "—"), p("Cargo", small), p(model["employee_position"] or "No registrado")],
        [p("Ingreso", small), p(model["admission_date"].strftime("%d/%m/%Y") if model["admission_date"] else "No registrado"), p("Periodo", small), p(model["period_display"])],
        [p("Pago", small), p(model["payment_method"]), p("Emisión", small), p(model["issued_date"])],
    ]
    employee_table = Table(employee_rows, colWidths=[25*mm, 63*mm, 18*mm, 58*mm])
    employee_table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),colors.white),("BOX",(0,0),(-1,-1),0.5,colors.HexColor("#d5deea")),
        ("INNERGRID",(0,0),(-1,-1),0.35,colors.HexColor("#d5deea")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
    ]))
    story.extend([p("DATOS DEL FUNCIONARIO Y PERÍODO", subheading), employee_table, Spacer(1, 2*mm)])

    lines = [[p("CONCEPTO", header_style), p("IMPORTE", header_style)]]
    for row in model["earnings"]:
        lines.append([p(row["label"]), p(gs(row["amount"]), amount_style)])
    lines.append([p("TOTAL HABERES", subheading), p(gs(model["gross"]), amount_style)])
    lines.append([p("DESCUENTOS", small), p("", small)])
    for row in model["deductions"]:
        lines.append([p(row["label"]), p(gs(row["amount"]), amount_style)])
    lines.append([p("TOTAL DESCUENTOS", subheading), p(gs(model["discounts"]), amount_style)])
    net_style = ParagraphStyle("NetTitle", parent=subheading, fontSize=11)
    net_amount_style = ParagraphStyle("NetAmount", parent=amount_style, fontSize=12, textColor=navy)
    lines.append([p("NETO A COBRAR", net_style), p(gs(model["net"]), net_amount_style)])
    concept_table = Table(lines, colWidths=[116*mm, 48*mm], repeatRows=1)
    concept_table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),navy),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("BOX",(0,0),(-1,-1),0.6,colors.HexColor("#cbd6e5")),("INNERGRID",(0,0),(-1,-1),0.3,colors.HexColor("#dfe5ee")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),7),
        ("RIGHTPADDING",(0,0),(-1,-1),7),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("BACKGROUND",(0,len(lines)-1),(-1,len(lines)-1),pale),
    ]))
    story.extend([p("DETALLE DE REMUNERACIONES Y DESCUENTOS", subheading), concept_table, Spacer(1, 4*mm)])
    if model["notes"]:
        story.extend([p("OBSERVACIONES", subheading), p(model["notes"], body), Spacer(1, 2*mm)])
    if model["warnings"]:
        story.append(p("VALIDACIONES PENDIENTES", subheading))
        for warning in model["warnings"][:10]:
            story.append(p("• " + warning, small))
    story.extend([
        Spacer(1, 7*mm),
        p("Las firmas acreditan la suscripción del presente recibo, pero no sustituyen la verificación del pago efectivo ni la revisión profesional de los conceptos y bases aplicables.", small),
        Spacer(1, 15*mm),
    ])
    signature_rows = [
        [p("____________________________________", centered), p("____________________________________", centered)],
        [p(model["representative"] or "Empleador / representante legal", centered), p(model["employee_name"], centered)],
        [p("Firma del empleador · Fecha: ____/____/______", small), p("Firma del funcionario · Fecha: ____/____/______", small)],
    ]
    sig_table = Table(signature_rows, colWidths=[82*mm,82*mm])
    sig_table.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
    story.extend([sig_table, Spacer(1, 5*mm), p(f"Generado por DIGIT-LABORAL · Registro #{model['record_id']} · Versión guardada e inmutable · No es un formulario oficial de MTESS ni IPS.", small)])

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d5deea"))
        canvas.line(18*mm, 14*mm, A4[0] - 18*mm, 14*mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(muted)
        canvas.drawString(18*mm, 9*mm, "DIGIT-LABORAL · Liquidación de Salarios")
        canvas.drawRightString(A4[0] - 18*mm, 9*mm, f"Página {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
