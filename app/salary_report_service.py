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
        warnings.append("Este cálculo está anulado. La descarga es una copia histórica identificada como ANULADA, no un recibo vigente.")

    # La asistencia y el medio de pago provienen del cálculo guardado o su
    # anexo vinculado, no de valores estimados. Nunca confundir fecha de
    # emisión con fecha efectiva de pago.
    from .salary_data import attendance_data
    attendance = attendance_data(db, item)
    actual_start = actual_end = None
    try:
        start_text = str(attendance.get("period_start") or "")
        end_text = str(attendance.get("period_end") or "")
        if start_text and end_text:
            actual_start, actual_end = date.fromisoformat(start_text), date.fromisoformat(end_text)
            if (period_start and period_end and
                    (actual_start < period_start or actual_end > period_end or actual_end < actual_start)):
                raise ValueError("Fuera de mes")
    except (ValueError, TypeError):
        warnings.append("Las fechas de asistencia vinculada no son válidas para el período. Verificá el anexo.")
        actual_start = actual_end = None
    if actual_start is not None and actual_end is not None:
        period_start, period_end = actual_start, actual_end

    payment_date_raw = (
        attendance.get("payment_date") or saved.get("payment_date") or
        saved.get("paid_on") or inputs.get("payment_date") or inputs.get("paid_on")
    )
    payment_date_display = "No registrada"
    if payment_date_raw:
        try:
            payment_date_display = date.fromisoformat(str(payment_date_raw)).strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            warnings.append("La fecha de pago guardada no es válida y no fue sustituida por la fecha de emisión.")

    def quantity(key: str, fallback: str = "No registrado") -> str:
        value = attendance.get(key)
        if value in (None, ""):
            return fallback
        try:
            from decimal import Decimal
            parsed = Decimal(str(value))
            if not parsed.is_finite() or parsed < 0:
                raise ValueError
            return str(int(parsed)) if parsed == parsed.to_integral_value() else format(parsed.normalize(), "f")
        except (ValueError, ArithmeticError, TypeError):
            warnings.append(f"El campo {key} contiene un valor inválido; revisá la asistencia guardada.")
            return fallback

    pieces_raw = (attendance.get("pieces_or_tasks") if attendance.get("pieces_or_tasks") not in (None, "")
                  else saved.get("pieces_or_tasks", inputs.get("pieces_or_tasks", inputs.get("tasks_count"))))
    pieces_display = clean_text(str(pieces_raw), max_length=90) if pieces_raw not in (None, "") else "No registrado"

    missing_receipt = []
    for key, name in (
        ("days_worked", "días trabajados"),
        ("hours_worked", "horas trabajadas"),
        ("payment_method", "forma de pago"),
        ("payment_date", "fecha real de pago"),
        ("pieces_or_tasks", "piezas o tareas (indicar 0 cuando no corresponde)"),
    ):
        if (attendance.get(key) in (None, "") and
                (key not in {"payment_date", "pieces_or_tasks"} or
                 ((not payment_date_raw) if key == "payment_date" else pieces_raw in (None, "")))):
            missing_receipt.append(name)
    if missing_receipt:
        warnings.append("Datos de recibo pendientes: " + ", ".join(missing_receipt) +
                        ". Completalos desde el anexo del recibo sin recalcular importes.")
    branding = db.scalar(select(CompanyBranding).where(CompanyBranding.company_id == company.id))
    issued_date = clean_text(str(saved.get("issued_date") or ""), max_length=40)
    if not issued_date and item.created_at:
        issued_date = item.created_at.strftime("%d/%m/%Y")
    representative = clean_text(str(company.legal_representative or (branding.signature_name if branding else "") or company.responsible_name or ""), max_length=180)
    payment_method = clean_text(str(attendance.get("payment_method") or identity.get("payment_method") or inputs.get("payment_method") or "No registrado"), max_length=80)

    return {
        "code": f"DL-LS-{item.id:06d}",
        "record_id": item.id,
        "period": period,
        "period_display": period_display,
        "period_start": period_start,
        "period_end": period_end,
        "period_from_display": period_start.strftime("%d/%m/%Y") if period_start else "No registrado",
        "period_to_display": period_end.strftime("%d/%m/%Y") if period_end else "No registrado",
        "days_worked_display": quantity("days_worked"),
        "hours_worked_display": quantity("hours_worked"),
        "pieces_or_tasks_display": pieces_display,
        "payment_date_display": payment_date_display,
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
        "is_annulled": item.status == "Anulado",
        "payment_date_iso": date.fromisoformat(str(payment_date_raw)).isoformat() if payment_date_display != "No registrada" else "",
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
    """Imprime original y duplicado con referencia DIGIT-LABORAL; sin QR."""
    from .salary_receipt_mtess_style import build_mtess_style_salary_pdf
    return build_mtess_style_salary_pdf(model)
