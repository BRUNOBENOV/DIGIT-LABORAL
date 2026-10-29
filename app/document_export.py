from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from .logo_presentation import prepare_company_logo

from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

META_PREFIX = "__DIGIT_META_V1__"

MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

DOCUMENT_LABELS: dict[str, str] = {
    "certificado_trabajo_a": "Certificado de Trabajo",
    "certificado_trabajo_b": "Certificado de Trabajo B",
    "constancia": "Constancia de Trabajo",
    "aguinaldo_anual": "Recibo de Pago de Aguinaldo",
    "aguinaldo_proporcional": "Liquidación de Aguinaldo Proporcional",
    "permiso_paternidad": "Solicitud de Permiso por Paternidad",
    "contrato_trabajo": "Contrato Individual de Trabajo",
    "contrato_tiempo_parcial": "Contrato Individual de Trabajo a Tiempo Parcial",
    "contrato_mipymes_plazo_determinado": "Contrato a Plazo Determinado para MIE / PE",
    "contrato_mipymes_80": "Contrato a Plazo Determinado MIE — Régimen Salarial Especial",
    "adenda_prorroga_contrato": "Adenda o Prórroga de Contrato de Trabajo",
    "ficha_empleado": "Ficha de Empleado",
    "solicitud_vacacion": "Solicitud de Vacaciones",
    "notificacion_vacaciones": "Notificación de Vacaciones al Trabajador",
    "usufructo_vacaciones": "Constancia de Usufructo de Vacaciones",
    "recibo_vacaciones": "Recibo de Pago de Vacaciones",
    "notificacion_preaviso": "Notificación de Preaviso",
    "renuncia": "Nota de Renuncia",
    "despido": "Comunicación de Despido",
    "permiso_laboral": "Solicitud de Permiso Laboral",
    "amonestacion": "Amonestación Escrita",
    "cambio_salarial": "Comunicación de Cambio Salarial",
    "alta_funcionario": "Constancia de Alta de Funcionario",
    "baja_funcionario": "Constancia de Baja de Funcionario",
    "recibo_salario": "Recibo de Salario",
    "liquidacion_final": "Liquidación Final",
}

SPECIAL_NUMBERS = {
    0: "cero",
    1: "uno",
    2: "dos",
    3: "tres",
    4: "cuatro",
    5: "cinco",
    6: "seis",
    7: "siete",
    8: "ocho",
    9: "nueve",
    10: "diez",
    11: "once",
    12: "doce",
    13: "trece",
    14: "catorce",
    15: "quince",
    16: "dieciséis",
    17: "diecisiete",
    18: "dieciocho",
    19: "diecinueve",
    20: "veinte",
    21: "veintiuno",
    22: "veintidós",
    23: "veintitrés",
    24: "veinticuatro",
    25: "veinticinco",
    26: "veintiséis",
    27: "veintisiete",
    28: "veintiocho",
    29: "veintinueve",
}
TENS = {30: "treinta", 40: "cuarenta", 50: "cincuenta", 60: "sesenta", 70: "setenta", 80: "ochenta", 90: "noventa"}
HUNDREDS = {
    100: "cien",
    200: "doscientos",
    300: "trescientos",
    400: "cuatrocientos",
    500: "quinientos",
    600: "seiscientos",
    700: "setecientos",
    800: "ochocientos",
    900: "novecientos",
}


@dataclass(frozen=True)
class ExportData:
    document_type: str
    title: str
    city: str
    issue_date: date
    company_name: str
    company_ruc: str = ""
    company_address: str = ""
    company_phone: str = ""
    company_email: str = ""
    legal_representative: str = ""
    signature_title: str = "Representante legal"
    logo_bytes: bytes | None = None
    logo_content_type: str = ""
    primary_color: str = "#173B86"
    secondary_color: str = "#0B1F48"
    document_footer: str = "Generado por Digit Laboral"
    employee_name: str = ""
    employee_document: str = ""
    position: str = ""
    admission_date: date | None = None
    salary: int = 0
    body: str = ""
    status: str = "Borrador"
    created_by: str = ""
    created_at: datetime | None = None
    metadata: dict[str, Any] | None = None


def format_date_long_es(value: date | datetime | None) -> str:
    if not value:
        return ""
    return f"{value.day} de {MONTHS_ES[value.month - 1]} de {value.year}"


def format_date_short(value: date | datetime | None) -> str:
    if not value:
        return ""
    return value.strftime("%d/%m/%Y")


def format_gs(value: int | float | None) -> str:
    return f"{int(round(value or 0)):,}".replace(",", ".")


def _apocopate(text: str) -> str:
    if text.endswith("veintiuno"):
        return text[:-9] + "veintiún"
    if text.endswith(" y uno"):
        return text[:-6] + " y un"
    if text.endswith("uno"):
        return text[:-3] + "un"
    return text


def _under_thousand(number: int) -> str:
    if number in SPECIAL_NUMBERS:
        return SPECIAL_NUMBERS[number]
    if number < 100:
        tens = (number // 10) * 10
        unit = number % 10
        return TENS[tens] if unit == 0 else f"{TENS[tens]} y {SPECIAL_NUMBERS[unit]}"
    hundreds = (number // 100) * 100
    remainder = number % 100
    prefix = "ciento" if hundreds == 100 and remainder else HUNDREDS[hundreds]
    return prefix if remainder == 0 else f"{prefix} {_under_thousand(remainder)}"


def number_to_words_es(number: int) -> str:
    number = int(number)
    if number < 0:
        return "menos " + number_to_words_es(abs(number))
    if number < 1000:
        return _under_thousand(number)
    if number < 1_000_000:
        thousands, remainder = divmod(number, 1000)
        prefix = "mil" if thousands == 1 else f"{_apocopate(number_to_words_es(thousands))} mil"
        return prefix if remainder == 0 else f"{prefix} {number_to_words_es(remainder)}"
    if number < 1_000_000_000:
        millions, remainder = divmod(number, 1_000_000)
        prefix = "un millón" if millions == 1 else f"{_apocopate(number_to_words_es(millions))} millones"
        return prefix if remainder == 0 else f"{prefix} {number_to_words_es(remainder)}"
    billions, remainder = divmod(number, 1_000_000_000)
    prefix = "mil millones" if billions == 1 else f"{_apocopate(number_to_words_es(billions))} mil millones"
    return prefix if remainder == 0 else f"{prefix} {number_to_words_es(remainder)}"


def guaranies_in_words(value: int) -> str:
    value = max(0, int(value or 0))
    return f"{_apocopate(number_to_words_es(value))} guaraníes"


def encode_metadata(notes: str = "", **metadata: Any) -> str:
    payload = {"notes": notes.strip(), **metadata}
    return META_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def decode_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {"notes": ""}
    if not raw.startswith(META_PREFIX):
        return {"notes": raw}
    try:
        payload = json.loads(raw[len(META_PREFIX) :])
        return payload if isinstance(payload, dict) else {"notes": ""}
    except (json.JSONDecodeError, TypeError):
        return {"notes": raw}


def optional_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _metadata_money(metadata: dict[str, Any], key: str, fallback: int = 0) -> int:
    value = metadata.get(key, fallback)
    try:
        return max(0, int(round(float(value or 0))))
    except (TypeError, ValueError, OverflowError):
        return max(0, int(fallback or 0))


def _salary_receipt_totals(metadata: dict[str, Any], salary: int) -> tuple[list[tuple[str, int]], list[tuple[str, int]], int, int, int]:
    incomes = [
        ("Salario básico", _metadata_money(metadata, "salary_basic_amount", salary)),
        ("Recargo nocturno", _metadata_money(metadata, "night_surcharge_amount")),
        ("Horas extras diurnas (50%)", _metadata_money(metadata, "overtime_day_amount")),
        ("Horas extras nocturnas (100%)", _metadata_money(metadata, "overtime_night_amount")),
        ("Trabajo en feriados", _metadata_money(metadata, "holiday_amount")),
        ("Remuneración por vacaciones", _metadata_money(metadata, "vacation_pay_amount")),
        ("Asignación familiar", _metadata_money(metadata, "family_allowance_amount")),
        ("Comisiones", _metadata_money(metadata, "commission_amount")),
        ("Gratificaciones", _metadata_money(metadata, "gratification_amount")),
        ("Premios", _metadata_money(metadata, "prize_amount")),
        ("Bonificaciones", _metadata_money(metadata, "bonus_amount")),
        (str(metadata.get("other_income_description") or "Otros ingresos").strip(), _metadata_money(metadata, "other_income_amount")),
    ]
    incomes = [(label, value) for label, value in incomes if value > 0 or label == "Salario básico"]
    deductions = [
        ("Aporte al seguro social (IPS)", _metadata_money(metadata, "ips_deduction_amount")),
        ("Anticipo de salario", _metadata_money(metadata, "advance_deduction_amount")),
        ("Cuotas autorizadas por escrito", _metadata_money(metadata, "authorized_deduction_amount")),
        ("Orden de autoridad competente", _metadata_money(metadata, "authority_deduction_amount")),
        (str(metadata.get("other_deduction_description") or "Otros descuentos permitidos").strip(), _metadata_money(metadata, "other_deduction_amount")),
    ]
    deductions = [(label, value) for label, value in deductions if value > 0]
    total_income = sum(value for _, value in incomes)
    total_deductions = sum(value for _, value in deductions)
    return incomes, deductions, total_income, total_deductions, total_income - total_deductions


def _settlement_totals(metadata: dict[str, Any]) -> tuple[list[tuple[str, int]], list[tuple[str, int]], int, int, int]:
    incomes = [
        ("Salarios pendientes", _metadata_money(metadata, "settlement_salary_due")),
        ("Preaviso, si corresponde", _metadata_money(metadata, "settlement_notice_amount")),
        ("Indemnización, si corresponde", _metadata_money(metadata, "settlement_indemnity_amount")),
        ("Vacaciones pendientes o proporcionales", _metadata_money(metadata, "settlement_vacation_amount")),
        ("Aguinaldo devengado o proporcional", _metadata_money(metadata, "settlement_bonus_amount")),
        (str(metadata.get("settlement_other_income_description") or "Otros haberes").strip(), _metadata_money(metadata, "settlement_other_income_amount")),
    ]
    incomes = [(label, value) for label, value in incomes if value > 0]
    deductions = [
        ("Aporte u otros descuentos legalmente procedentes", _metadata_money(metadata, "settlement_ips_deduction")),
        (str(metadata.get("settlement_other_deduction_description") or "Otros descuentos sujetos a validación").strip(), _metadata_money(metadata, "settlement_other_deduction")),
    ]
    deductions = [(label, value) for label, value in deductions if value > 0]
    total_income = sum(value for _, value in incomes)
    total_deductions = sum(value for _, value in deductions)
    return incomes, deductions, total_income, total_deductions, total_income - total_deductions


def document_detail_table_data(document_type: str, metadata: dict[str, Any] | None = None, salary: int = 0) -> dict[str, Any] | None:
    """Structured detail used by the live print, Word and PDF views."""
    meta = metadata or {}
    if document_type == "recibo_salario":
        incomes, deductions, total_income, total_deductions, net = _salary_receipt_totals(meta, salary)
        rows: list[dict[str, Any]] = [{"cells": ["INGRESOS", "", ""], "style": "section"}]
        rows.extend({"cells": [label, format_gs(value), ""], "style": "normal"} for label, value in incomes)
        rows.append({"cells": ["TOTAL INGRESOS", format_gs(total_income), ""], "style": "total"})
        rows.append({"cells": ["DESCUENTOS", "", ""], "style": "section"})
        if deductions:
            rows.extend({"cells": [label, "", format_gs(value)], "style": "normal"} for label, value in deductions)
        else:
            rows.append({"cells": ["Sin descuentos registrados", "", "0"], "style": "normal"})
        rows.append({"cells": ["TOTAL DESCUENTOS", "", format_gs(total_deductions)], "style": "total"})
        rows.append({"cells": ["NETO A PERCIBIR", format_gs(net), ""], "style": "grand"})
        return {
            "title": "DETALLE DE LA LIQUIDACIÓN DE SALARIO",
            "headers": ["Concepto", "Haberes (Gs.)", "Descuentos (Gs.)"],
            "rows": rows,
        }

    if document_type == "liquidacion_final":
        incomes, deductions, total_income, total_deductions, net = _settlement_totals(meta)
        if not incomes and _metadata_money(meta, "amount") > 0:
            incomes = [("Importe total consignado para revisión", _metadata_money(meta, "amount"))]
            total_income = incomes[0][1]
            net = total_income - total_deductions
        rows = [{"cells": ["HABERES", "", ""], "style": "section"}]
        rows.extend({"cells": [label, format_gs(value), ""], "style": "normal"} for label, value in incomes)
        rows.append({"cells": ["TOTAL HABERES", format_gs(total_income), ""], "style": "total"})
        rows.append({"cells": ["DESCUENTOS (verificar procedencia)", "", ""], "style": "section"})
        rows.extend({"cells": [label, "", format_gs(value)], "style": "normal"} for label, value in deductions)
        if not deductions:
            rows.append({"cells": ["Sin descuentos consignados", "", "0"], "style": "normal"})
        rows.append({"cells": ["TOTAL DESCUENTOS", "", format_gs(total_deductions)], "style": "total"})
        rows.append({"cells": ["NETO A LIQUIDAR", format_gs(net), ""], "style": "grand"})
        return {
            "title": "CUADRO DE HABERES Y DESCUENTOS — SUJETO A REVISIÓN",
            "headers": ["Concepto", "Haberes (Gs.)", "Descuentos (Gs.)"],
            "rows": rows,
        }

    if document_type in {"aguinaldo_anual", "aguinaldo_proporcional"}:
        period_start = format_date_short(optional_date(meta.get("period_start"))) or "A completar"
        period_end = format_date_short(optional_date(meta.get("period_end"))) or "A completar"
        amount = _metadata_money(meta, "amount", salary)
        date_paid = format_date_short(optional_date(meta.get("payment_date"))) or "A completar"
        return {
            "title": "DETALLE DEL AGUINALDO",
            "headers": ["Concepto", "Detalle"],
            "rows": [
                {"cells": ["Período considerado", f"{period_start} al {period_end}"], "style": "normal"},
                {"cells": ["Fecha de pago", date_paid], "style": "normal"},
                {"cells": ["Importe abonado (Gs.)", format_gs(amount)], "style": "grand"},
            ],
        }

    if document_type in {"notificacion_vacaciones", "usufructo_vacaciones", "recibo_vacaciones"}:
        period_start = format_date_short(optional_date(meta.get("leave_start"))) or "A completar"
        period_end = format_date_short(optional_date(meta.get("leave_end"))) or "A completar"
        amount = _metadata_money(meta, "vacation_amount", _metadata_money(meta, "amount"))
        year_value = str(meta.get("vacation_period_year") or "A completar")
        request_date = format_date_short(optional_date(meta.get("vacation_request_date"))) or "A completar"
        notice_date = format_date_short(optional_date(meta.get("vacation_notice_date"))) or "A completar"
        days = str(meta.get("vacation_days") or "A completar")
        rows = [
            {"cells": ["Período de vacaciones", f"{period_start} al {period_end}"], "style": "normal"},
            {"cells": ["Período anual al que corresponden", year_value], "style": "normal"},
            {"cells": ["Días consignados", days], "style": "normal"},
            {"cells": ["Fecha de solicitud", request_date], "style": "normal"},
            {"cells": ["Fecha de comunicación al trabajador", notice_date], "style": "normal"},
        ]
        if document_type == "recibo_vacaciones":
            rows.extend([
                {"cells": ["Fecha de pago", format_date_short(optional_date(meta.get("payment_date"))) or "A completar"], "style": "normal"},
                {"cells": ["Remuneración abonada (Gs.)", format_gs(amount)], "style": "grand"},
            ])
        elif amount > 0:
            rows.append({"cells": ["Remuneración asociada (Gs.)", format_gs(amount)], "style": "total"})
        return {
            "title": "DATOS DEL PERÍODO DE VACACIONES",
            "headers": ["Dato", "Detalle"],
            "rows": rows,
        }
    return None


def build_document_body(
    document_type: str,
    *,
    company_name: str,
    employee_name: str,
    employee_document: str,
    position: str,
    admission_date: date | None,
    salary: int,
    issue_date: date,
    city: str,
    metadata: dict[str, Any],
    company_ruc: str = "",
    company_address: str = "",
    company_phone: str = "",
    company_email: str = "",
    legal_representative: str = "",
    employee_address: str = "",
    employee_phone: str = "",
    employee_email: str = "",
    employee_birth_date: date | None = None,
) -> tuple[str, str]:
    if document_type not in DOCUMENT_LABELS:
        raise ValueError("Tipo de documento no soportado")

    title = DOCUMENT_LABELS[document_type]
    notes = str(metadata.get("notes", "")).strip()
    identity = employee_name
    if employee_document:
        identity += f", con C.I. N.º {employee_document}"
    certificate_subject = f"{employee_name}, con C.I. N.º {employee_document}," if employee_document else employee_name
    role = position or "el cargo registrado en su legajo"
    admission = format_date_long_es(admission_date) or "la fecha registrada en su legajo"
    salary_display = f"Gs. {format_gs(salary)} ({guaranies_in_words(salary)})" if salary else "la remuneración registrada en su legajo"
    period_start = optional_date(metadata.get("period_start"))
    period_end = optional_date(metadata.get("period_end"))
    effective_date = optional_date(metadata.get("effective_date"))
    leave_start = optional_date(metadata.get("leave_start"))
    leave_end = optional_date(metadata.get("leave_end"))
    amount = _metadata_money(metadata, "amount", salary)
    amount_words = guaranies_in_words(amount)
    last_period_salary = _metadata_money(metadata, "last_period_salary_amount", 0)
    last_period_salary_display = (
        f"Gs. {format_gs(last_period_salary)} ({guaranies_in_words(last_period_salary)})"
        if last_period_salary > 0 else "importe a completar según el último período de pago"
    )
    employment_end = format_date_long_es(effective_date)
    recipient = str(metadata.get("recipient") or "Encargado/a de Recursos Humanos").strip()
    nationality = str(metadata.get("nationality") or "paraguaya").strip()
    civil_status = str(metadata.get("civil_status") or "").strip()
    include_current_salary = str(metadata.get("include_salary", "on") or "").lower() in {"on", "true", "1"}
    modality = str(metadata.get("contract_modality") or "").strip()
    modality_labels = {
        "indefinido": "por tiempo indefinido",
        "plazo_fijo": "a plazo determinado, sujeto a causa temporal lícita y verificable",
        "tiempo_parcial": "a tiempo parcial, con la jornada específica consignada en este instrumento",
        "mipyme_plazo_fijo": "a plazo determinado en el marco del régimen aplicable a MIE/PE, sujeto a la verificación de elegibilidad",
        "mipyme_80": "a plazo determinado con base salarial especial del 80%, exclusivamente sujeto a los requisitos legales vigentes para MIE",
        "prorroga": "por prórroga o adenda al contrato anterior expresamente identificado",
    }
    modality_label = modality_labels.get(modality, "según la modalidad seleccionada y validada por las partes")
    contract_end = format_date_long_es(optional_date(metadata.get("contract_end_date"))) or "la fecha de finalización que debe completarse"
    functions = str(metadata.get("job_functions") or "").strip() or "COMPLETAR: detallar las tareas y responsabilidades principales"
    workplace = str(metadata.get("workplace") or "").strip() or "COMPLETAR: indicar el establecimiento o lugar de prestación"
    schedule = str(metadata.get("work_schedule") or "").strip() or "COMPLETAR: indicar días, horario y descansos aplicables"
    weekly_rest = str(metadata.get("weekly_rest") or "").strip() or "según la jornada y descansos legalmente aplicables"
    pay_frequency = str(metadata.get("payment_frequency") or "Mensual").strip()
    probation = str(metadata.get("probation_period") or "").strip() or "según procedencia legal y acuerdo escrito"
    contract_cause = str(metadata.get("contract_cause") or "").strip() or "COMPLETAR: describir y documentar la causa objetiva que justifica el plazo"
    contract_reference = str(metadata.get("previous_contract_number") or "").strip() or "COMPLETAR: identificar contrato anterior, fecha y vigencia"
    end_date_text = format_date_long_es(optional_date(metadata.get("contract_end_date"))) or "A completar"
    payment_date = format_date_short(optional_date(metadata.get("payment_date"))) or "A completar"
    vacation_start = format_date_short(leave_start) or "A completar"
    vacation_end = format_date_short(leave_end) or "A completar"
    termination_reason = str(metadata.get("termination_reason") or "").strip() or "COMPLETAR: indicar el motivo específico y la documentación de respaldo"
    incident_details = str(metadata.get("incident_details") or "").strip() or notes or "COMPLETAR: describir los hechos concretos, fecha, lugar y antecedentes"
    disciplinary_action = str(metadata.get("disciplinary_action") or "Amonestación escrita").strip()
    sanction_start = format_date_short(optional_date(metadata.get("sanction_start_date"))) or "No aplica / completar"
    sanction_end = format_date_short(optional_date(metadata.get("sanction_end_date"))) or "No aplica / completar"
    employee_address_text = employee_address or "un domicilio no consignado en el legajo"
    company_address_clause = f", ubicada sobre la calle {company_address}" if company_address else ""
    employer_id = company_name
    if company_ruc:
        employer_id += f", RUC {company_ruc}"
    if company_address:
        employer_id += f", con domicilio en {company_address}"
    if legal_representative:
        employer_id += f", representada por {legal_representative}"
    employee_detail = employee_name
    if employee_document:
        employee_detail += f", C.I. N.º {employee_document}"
    if employee_address:
        employee_detail += f", domiciliado/a en {employee_address}"

    payroll_incomes, payroll_deductions, payroll_gross, payroll_deduction_total, payroll_net = _salary_receipt_totals(metadata, salary)
    settlement_incomes, settlement_deductions, settlement_gross, settlement_deduction_total, settlement_net = _settlement_totals(metadata)

    bodies: dict[str, str] = {
                "certificado_trabajo_a": (
            "C E R T I F I C O:\n\n"
            + (
                f"Que {certificate_subject} prestó servicios en la firma comercial {company_name}, "
                f"desde el {admission} hasta el {employment_end}, desempeñándose como {role}.\n"
                f"Salario devengado durante el último período de pago: {last_period_salary_display}."
                if effective_date else
                f"Que {identity} presta servicios en la firma comercial {company_name} desde el {admission}, "
                f"desempeñándose como {role}."
                + (f" Percibe una remuneración mensual registrada de {salary_display}." if include_current_salary else "")
            )
        ),
        "certificado_trabajo_b": (
            "C E R T I F I C O:\n\n"
            + (
                f"Que {certificate_subject} prestó servicios en la firma comercial {company_name}, "
                f"desde el {admission} hasta el {employment_end}, desempeñándose como {role}.\n"
                f"Salario devengado durante el último período de pago: {last_period_salary_display}."
                if effective_date else
                f"Que {identity} presta servicios en la firma comercial {company_name} desde el {admission}, "
                f"desempeñándose como {role}."
                + (f" Percibe una remuneración mensual registrada de {salary_display}." if include_current_salary else "")
            )
        ),
        "constancia": (
            "C E R T I F I C O:\n\n"
            + (
                f"Que {certificate_subject} prestó servicios en la firma comercial {company_name}, "
                f"desde el {admission} hasta el {employment_end}, desempeñándose como {role}.\n"
                f"Salario devengado durante el último período de pago: {last_period_salary_display}."
                if effective_date else
                f"Que {identity}, de nacionalidad {nationality.upper()}"
                + (f", de estado civil {civil_status.upper()}" if civil_status else "")
                + (f", domiciliado/a en {employee_address}" if employee_address else "")
                + f", es empleado/a de la firma comercial {company_name}{company_address_clause}, "
                + f"desde el {admission}, desempeñándose como {role}."
                + (f" Percibe una remuneración mensual registrada de {salary_display}." if include_current_salary else "")
                + "\n\nSe expide la presente constancia para los fines y efectos a que hubiere lugar."
            )
        ),
        "aguinaldo_anual": (
            f"El empleador {company_name} deja constancia de haber abonado a {identity} la suma de Gs. {format_gs(amount)} "
            f"({amount_words}), en concepto de aguinaldo correspondiente al período comprendido entre el "
            f"{format_date_short(period_start) or 'A completar'} y el {format_date_short(period_end) or 'A completar'}, "
            "conforme al artículo 243 del Código del Trabajo. El cálculo debe guardar correspondencia con las remuneraciones computables del período.\n\n"
            f"Fecha de pago consignada: {payment_date}. La firma acredita recepción del importe indicado, sin implicar renuncia a otros derechos legalmente reconocidos."
        ),
        "aguinaldo_proporcional": (
            f"Se consigna una liquidación de aguinaldo proporcional a favor de {identity}, correspondiente al período comprendido entre "
            f"el {format_date_short(period_start) or 'A completar'} y el {format_date_short(period_end) or 'A completar'}, por Gs. {format_gs(amount)} "
            f"({amount_words}).\n\nEl importe y las remuneraciones computables deberán coincidir con el cálculo vinculado y revisarse antes del pago, conforme al artículo 244 del Código del Trabajo. "
            f"Fecha de pago consignada: {payment_date}."
        ),
        "permiso_paternidad": (
            f"Señor/a\n{recipient}\n{company_name}\n\nRef.: Solicitud de permiso por paternidad\n\n"
            f"Yo, {identity}, trabajador/a de la empresa, solicito el permiso por paternidad que corresponda conforme a la normativa vigente, "
            f"desde el {vacation_start} hasta el {vacation_end}. "
            f"{'Fecha del nacimiento o hecho generador: ' + format_date_short(optional_date(metadata.get('birth_event_date'))) + '.' if optional_date(metadata.get('birth_event_date')) else 'Se adjuntará o indicará la documentación que acredite el hecho generador, según corresponda.'}\n\n"
            "La aprobación, el cómputo y el registro del permiso deberán ajustarse a la legislación vigente y a la documentación respaldatoria."
        ),
        "contrato_trabajo": (
            "BORRADOR CONTRACTUAL — REVISAR Y COMPLETAR ANTES DE FIRMAR.\n\n"
            f"En {city}, a los {format_date_long_es(issue_date)}, comparecen {employer_id}, en adelante EL EMPLEADOR, "
            f"y {employee_detail}, en adelante EL TRABAJADOR/A, y acuerdan celebrar un contrato individual de trabajo {modality_label}, bajo las cláusulas siguientes.\n\n"
            f"PRIMERA — FUNCIONES Y LUGAR DE TRABAJO. EL TRABAJADOR/A prestará servicios en el cargo de {role}. Funciones principales: {functions}. "
            f"Lugar o establecimiento: {workplace}.\n\n"
            f"SEGUNDA — INICIO, DURACIÓN Y PRUEBA. La relación inicia el {admission}. La modalidad acordada es {modality_label}. "
            f"{'La fecha de finalización prevista es ' + contract_end + '. ' if modality in {'plazo_fijo', 'mipyme_plazo_fijo', 'mipyme_80', 'prorroga'} else ''}"
            f"Período de prueba: {probation}. La duración y la causa del plazo deben ser compatibles con la modalidad y legislación aplicable.\n\n"
            f"TERCERA — JORNADA Y DESCANSOS. Jornada y horario: {schedule}. Descanso semanal: {weekly_rest}. Las partes deberán respetar los límites legales de jornada, descansos y recargos.\n\n"
            f"CUARTA — REMUNERACIÓN Y PAGO. La remuneración consignada es de {salary_display}, con periodicidad de pago {pay_frequency}. "
            "El salario no podrá ser inferior al mínimo legal aplicable, salvo régimen especial que resulte legalmente procedente y esté debidamente acreditado. "
            "Los descuentos se limitarán a los permitidos por la legislación vigente.\n\n"
            f"QUINTA — SEGURIDAD SOCIAL Y REGISTRO. El empleador realizará los registros y comunicaciones que correspondan ante las instituciones competentes. "
            "Este documento no sustituye las altas, comunicaciones ni registros requeridos por MTESS o IPS.\n\n"
            "SEXTA — DERECHOS Y OBLIGACIONES. Ambas partes cumplirán el Código del Trabajo, las normas de seguridad social, el reglamento interno vigente y las condiciones aquí consignadas. "
            "Las modificaciones se documentarán por escrito cuando corresponda.\n\n"
            "SÉPTIMA — TERMINACIÓN. La terminación de la relación se regirá por la legislación aplicable, sus causas, procedimientos, preavisos y liquidaciones correspondientes. "
            "Ninguna cláusula se interpretará como renuncia anticipada a derechos irrenunciables.\n\n"
            f"CONDICIONES ESPECÍFICAS / CAUSA DEL PLAZO: {contract_cause}\n\n"
            f"REFERENCIA DE CONTRATO ANTERIOR, SI ES ADENDA: {contract_reference}\n\n"
            "Las partes declaran haber leído el documento y recibir un ejemplar. Antes de firmar, completar campos pendientes, verificar la modalidad elegida y contrastar el texto con el modelo oficial vigente del MTESS."
        ),
        "contrato_tiempo_parcial": (
            "BORRADOR DE CONTRATO A TIEMPO PARCIAL — REVISIÓN PROFESIONAL OBLIGATORIA.\n\n"
            f"En {city}, a los {format_date_long_es(issue_date)}, entre {employer_id} y {employee_detail}, se acuerda la prestación de servicios a tiempo parcial.\n\n"
            f"Cargo y tareas: {role}. Funciones: {functions}. Lugar de trabajo: {workplace}. Inicio: {admission}.\n\n"
            f"Jornada parcial pactada: {schedule}. Descanso semanal: {weekly_rest}. Remuneración pactada: {salary_display}; forma y periodicidad de pago: {pay_frequency}.\n\n"
            f"El contrato, la jornada y la remuneración deben verificarse frente a la regulación vigente del trabajo a tiempo parcial, incluidos los registros y aportes correspondientes. Período de prueba, si procede: {probation}.\n\n"
            "Las partes se obligan a cumplir la legislación laboral y de seguridad social aplicable. Debe utilizarse como base de trabajo y cotejarse con el modelo oficial vigente del MTESS antes de la firma."
        ),
        "contrato_mipymes_plazo_determinado": (
            "BORRADOR ADAPTADO — CONTRATO A PLAZO DETERMINADO PARA MIE / PE. REQUIERE VERIFICACIÓN DE ELEGIBILIDAD.\n\n"
            f"En {city}, a los {format_date_long_es(issue_date)}, comparecen {employer_id}, y {employee_detail}, quienes celebran el presente contrato bajo la modalidad temporal aplicable a MIE/PE, si reúnen los requisitos previstos en la Ley N.º 7444/2025, el Decreto N.º 4535/2025 y la Resolución MTESS N.º 220/2026.\n\n"
            f"Cargo y funciones: {role}. {functions}. Lugar de prestación: {workplace}. Fecha de inicio: {admission}. Fecha de finalización prevista: {contract_end}.\n\n"
            f"Jornada y horario: {schedule}. Descanso semanal: {weekly_rest}. Remuneración: {salary_display}. Periodicidad de pago: {pay_frequency}.\n\n"
            f"Causa objetiva y verificable que justifica el plazo determinado: {contract_cause}.\n\n"
            "La empresa debe confirmar su categorización como MIE/PE, los límites de duración y la procedencia de esta modalidad, registrar y validar el contrato por el procedimiento vigente, y entregar copia a la persona trabajadora. "
            "Este borrador no acredita por sí solo la elegibilidad ni sustituye el registro oficial."
        ),
        "contrato_mipymes_80": (
            "BORRADOR ADAPTADO — MODELO MIE A PLAZO DETERMINADO CON RÉGIMEN SALARIAL ESPECIAL. USO RESTRINGIDO.\n\n"
            f"En {city}, a los {format_date_long_es(issue_date)}, comparecen {employer_id}, y {employee_detail}, bajo la modalidad temporal y la base salarial especial que solo podrá utilizarse si se verifican los presupuestos legales aplicables a microempresas.\n\n"
            f"Cargo y funciones: {role}. {functions}. Lugar: {workplace}. Inicio: {admission}. Finalización prevista: {contract_end}.\n\n"
            f"Jornada y horario: {schedule}. Descanso semanal: {weekly_rest}. Remuneración consignada: {salary_display}. Periodicidad: {pay_frequency}.\n\n"
            f"Causa temporal documentada: {contract_cause}.\n\n"
            "Antes de utilizar este instrumento se deberá confirmar la categorización, los requisitos del régimen del ochenta por ciento, el salario mínimo aplicable, el límite temporal y el procedimiento de registro conforme a la Ley N.º 7444/2025, el Decreto N.º 4535/2025 y la Resolución MTESS N.º 220/2026. "
            "No aplicar este régimen por defecto ni sin acreditación documental."
        ),
        "adenda_prorroga_contrato": (
            "BORRADOR DE ADENDA / PRÓRROGA DE CONTRATO — REVISAR EL CONTRATO BASE.\n\n"
            f"En {city}, a los {format_date_long_es(issue_date)}, comparecen {employer_id}, y {employee_detail}, y dejan constancia de que el contrato anterior identificado como {contract_reference} "
            f"se modifica exclusivamente para extender o precisar la vigencia hasta el {contract_end}.\n\n"
            f"Cargo: {role}. Funciones/tareas vigentes o modificadas: {functions}. Lugar de trabajo: {workplace}. Jornada y horario: {schedule}. Descanso semanal: {weekly_rest}. Remuneración vigente: {salary_display}. Periodicidad: {pay_frequency}.\n\n"
            f"Motivo y condiciones de la prórroga: {contract_cause}.\n\n"
            "Las cláusulas no modificadas conservan su vigencia siempre que sean compatibles con la normativa aplicable. La adenda no debe utilizarse para eludir los límites legales de contratación a plazo fijo. "
            "Adjuntar e identificar el contrato original, verificar los requisitos y registrar el instrumento cuando corresponda."
        ),
        "ficha_empleado": (
            f"FICHA INDIVIDUAL DE PERSONAL\n\nEMPRESA: {company_name}\nRUC: {company_ruc or 'No consignado'}\n"
            f"FUNCIONARIO/A: {employee_name}\nCÉDULA: {employee_document or 'No consignada'}\n"
            f"FECHA DE NACIMIENTO: {format_date_short(employee_birth_date) or 'No consignada'}\n"
            f"NACIONALIDAD: {nationality}\nESTADO CIVIL: {civil_status or 'No consignado'}\n"
            f"DOMICILIO: {employee_address_text}\nTELÉFONO: {employee_phone or 'No consignado'}\nCORREO: {employee_email or 'No consignado'}\n"
            f"CARGO: {role}\nFECHA DE INGRESO: {admission}\nSALARIO REGISTRADO: {salary_display}\n"
            f"TIPO DE CONTRATO: {getattr(metadata, 'contract_type', '') or metadata.get('contract_type') or 'Ver legajo'}\n"
            f"OBSERVACIONES DEL LEGAJO: {notes or 'Sin observaciones'}\n\n"
            "Documento interno de administración de personal. Mantener actualizado y resguardar el acceso a los datos personales."
        ),
        "solicitud_vacacion": (
            f"Señor/a\n{recipient}\n{company_name}\n\nRef.: Solicitud de vacaciones\n\n"
            f"Yo, {identity}, solicito el usufructo de vacaciones correspondiente al período {metadata.get('vacation_period_year') or 'A completar'}, "
            f"desde el {vacation_start} hasta el {vacation_end}. Días solicitados: {metadata.get('vacation_days') or 'A completar'}.\n\n"
            f"Fecha de solicitud: {format_date_short(optional_date(metadata.get('vacation_request_date'))) or format_date_short(issue_date)}. "
            "La solicitud queda sujeta a revisión del saldo de días, aprobación y comunicación escrita de la empresa.\n\n"
            "Firma de la persona trabajadora y constancia de recepción/aprobación de la empresa."
        ),
        "notificacion_vacaciones": (
            f"NOTIFICACIÓN AL TRABAJADOR/A\n\nA: {identity}\nDe: {company_name}\n\n"
            f"Por la presente se comunica la concesión/programación de vacaciones correspondientes al período {metadata.get('vacation_period_year') or 'A completar'}, "
            f"desde el {vacation_start} hasta el {vacation_end}, por {metadata.get('vacation_days') or 'A completar'} día(s) consignado(s).\n\n"
            f"Fecha de solicitud registrada: {format_date_short(optional_date(metadata.get('vacation_request_date'))) or 'A completar'}. "
            f"Fecha de comunicación: {format_date_short(optional_date(metadata.get('vacation_notice_date'))) or format_date_short(issue_date)}.\n\n"
            f"Remuneración por vacaciones consignada, si corresponde: Gs. {format_gs(_metadata_money(metadata, 'vacation_amount'))}. "
            "La empresa debe comprobar saldo, remuneración, fechas y registro laboral antes de emitir esta notificación. La firma de recepción no implica renuncia a derechos."
        ),
        "usufructo_vacaciones": (
            f"{company_name} deja constancia de que {identity}, quien se desempeña como {role}, usufructó o usufructará vacaciones correspondientes al período "
            f"{metadata.get('vacation_period_year') or 'A completar'}, desde el {vacation_start} hasta el {vacation_end}.\n\n"
            f"Días consignados: {metadata.get('vacation_days') or 'A completar'}. Fecha de solicitud: "
            f"{format_date_short(optional_date(metadata.get('vacation_request_date'))) or 'A completar'}. Fecha de comunicación: "
            f"{format_date_short(optional_date(metadata.get('vacation_notice_date'))) or 'A completar'}.\n\n"
            "La empresa deberá conservar la anotación del período, duración y remuneración correspondiente en los registros laborales pertinentes."
        ),
        "recibo_vacaciones": (
            f"RECIBO DE PAGO DE VACACIONES\n\nEl empleador {company_name} declara haber abonado a {identity} la suma de "
            f"Gs. {format_gs(_metadata_money(metadata, 'vacation_amount', amount))} "
            f"({guaranies_in_words(_metadata_money(metadata, 'vacation_amount', amount))}), en concepto de remuneración por vacaciones del período "
            f"{metadata.get('vacation_period_year') or 'A completar'}, a usufructuarse desde el {vacation_start} hasta el {vacation_end}.\n\n"
            f"Fecha de pago consignada: {payment_date}. El recibo debe reflejar el importe realmente abonado y entregarse en ejemplares para ambas partes."
        ),
        "notificacion_preaviso": (
            f"NOTIFICACIÓN DE PREAVISO\n\nA: {employee_detail}\nEmpleador: {employer_id}\n\n"
            f"Por medio de la presente, se notifica el preaviso relacionado con la terminación de la relación laboral, con fecha efectiva consignada para el "
            f"{format_date_long_es(effective_date) or 'A completar'}. Fecha de inicio del preaviso: "
            f"{format_date_short(optional_date(metadata.get('notice_start_date'))) or format_date_short(issue_date)}. "
            f"Plazo informado: {metadata.get('notice_days') or 'A completar'} día(s).\n\n"
            f"Motivo o contexto que debe ser revisado antes de la entrega: {termination_reason}.\n\n"
            "El empleador debe comprobar los plazos, supuestos legales, medio de comunicación y efectos aplicables al caso concreto. "
            "La firma del destinatario acredita únicamente recepción, no conformidad con el contenido."
        ),
        "renuncia": (
            f"Señor/a\n{recipient}\n{company_name}\n\nRef.: Comunicación de renuncia\n\n"
            f"Yo, {identity}, comunico mi decisión de renunciar al puesto de {role}, con fecha efectiva o último día de trabajo consignado para el "
            f"{format_date_long_es(effective_date) or 'A completar'}.\n\n"
            "Solicito la liquidación de los haberes que legalmente correspondan y la entrega de los documentos de cierre de la relación laboral. "
            "La recepción de esta nota debe dejar constancia de la fecha en que fue presentada."
        ),
        "despido": (
            "BORRADOR DE COMUNICACIÓN DE TERMINACIÓN — REVISIÓN LEGAL OBLIGATORIA.\n\n"
            f"A: {employee_detail}\nEmpleador: {employer_id}\n\n"
            f"Se comunica la decisión de terminar la relación laboral con fecha efectiva consignada para el {format_date_long_es(effective_date) or 'A completar'}.\n\n"
            f"Motivo y circunstancias: {termination_reason}.\n\n"
            "Antes de emitir, verificar causal invocada, antecedentes y pruebas, procedimiento, preaviso, estabilidad especial si existiere y liquidación completa. "
            "No utilizar este borrador como una calificación automática de justa causa ni como sustituto de revisión jurídica individual."
        ),
        "permiso_laboral": (
            f"Señor/a\n{recipient}\n{company_name}\n\nRef.: Solicitud de permiso laboral\n\n"
            f"Yo, {identity}, solicito permiso de tipo «{metadata.get('leave_type') or 'A especificar'}» "
            f"desde el {vacation_start} hasta el {vacation_end}. Cantidad consignada: {metadata.get('leave_quantity') or 'A completar'} "
            f"{metadata.get('leave_unit') or 'unidad(es)'}.\n\n"
            f"Modalidad propuesta: {metadata.get('paid_leave') or 'A resolver'}; compensación o recuperación de horas, si procede: "
            f"{metadata.get('compensation_method') or 'A resolver'}.\n\n"
            "La autorización debe quedar documentada por la empresa y comunicarse según el tipo de licencia o permiso."
        ),
        "amonestacion": (
            "BORRADOR DE SANCIÓN DISCIPLINARIA — REVISIÓN PROFESIONAL OBLIGATORIA.\n\n"
            f"A: {employee_detail}\nEmpleador: {employer_id}\nMedida consignada: {disciplinary_action}.\n"
            f"Fecha del hecho: {format_date_short(optional_date(metadata.get('incident_date'))) or 'A completar'}.\n"
            f"Período de la medida, si corresponde: {sanction_start} al {sanction_end}.\n\n"
            f"Descripción objetiva de los hechos: {incident_details}.\n\n"
            "Antes de la entrega, comprobar el reglamento interno aplicable, la tipificación de la falta, antecedentes, proporcionalidad y derecho de defensa. "
            "La constancia de recepción no debe presentarse como admisión de responsabilidad."
        ),
        "cambio_salarial": (
            f"{company_name} comunica a {identity} que, a partir del {format_date_long_es(effective_date) or 'A completar'}, "
            f"la remuneración mensual consignada será de Gs. {format_gs(amount)} ({amount_words}). "
            f"Remuneración anterior, si aplica: Gs. {format_gs(_metadata_money(metadata, 'previous_salary'))}.\n\n"
            "La modificación debe documentarse de forma consistente con el acuerdo de las partes, los registros de nómina y las comunicaciones aplicables. "
            "Esta nota no autoriza descuentos ni renuncia a derechos adquiridos."
        ),
        "alta_funcionario": (
            f"CONSTANCIA INTERNA DE ALTA\n\n{company_name} deja constancia, para fines administrativos internos, del ingreso de {identity} "
            f"al cargo de {role}, a partir del {admission}, con remuneración registrada de {salary_display}.\n\n"
            "Esta constancia interna no sustituye la comunicación de entrada ni la documentación exigida por MTESS, IPS u otra institución."
        ),
        "baja_funcionario": (
            f"CONSTANCIA INTERNA DE BAJA\n\n{company_name} deja constancia, para fines administrativos internos, del cese de servicios de {identity}, "
            f"con fecha efectiva consignada para el {format_date_long_es(effective_date) or 'A completar'}.\n\n"
            f"Motivo registrado: {termination_reason}. Último día trabajado consignado: "
            f"{format_date_short(optional_date(metadata.get('last_worked_date'))) or 'A completar'}.\n\n"
            "Esta constancia no sustituye la comunicación de salida ni la liquidación final que correspondan ante los organismos y según la normativa."
        ),
        "recibo_salario": (
            f"LIQUIDACIÓN DE SALARIO — DETALLE DEL PERÍODO\n\nEmpleador: {employer_id}\nTrabajador/a: {employee_detail}\n"
            f"Período liquidado: {format_date_short(period_start) or 'A completar'} al {format_date_short(period_end) or 'A completar'}.\n"
            f"Fecha de pago: {payment_date}. Medio de pago: {metadata.get('payment_method') or 'A completar'}.\n"
            f"Jornadas trabajadas y pagadas: {metadata.get('days_worked') or 'A completar'}. "
            f"Horas trabajadas: {metadata.get('hours_worked') or 'A completar'}. "
            f"Piezas o tareas, si corresponde: {metadata.get('units_worked') or 'No aplica / completar'}.\n\n"
            f"Total de haberes consignados: Gs. {format_gs(payroll_gross)}. Total de descuentos consignados: Gs. {format_gs(payroll_deduction_total)}. "
            f"Neto a percibir: Gs. {format_gs(payroll_net)} ({guaranies_in_words(max(payroll_net, 0))}).\n\n"
            "La liquidación debe identificar cada concepto de ingreso y cada descuento. Solo deben incluirse descuentos admitidos por la legislación aplicable y debidamente respaldados. "
            "La firma del trabajador acredita la recepción del importe efectivamente pagado; el original se conserva por el empleador y el duplicado se entrega al trabajador."
        ),
        "liquidacion_final": (
            "BORRADOR DE LIQUIDACIÓN FINAL — REVISIÓN DE CÁLCULO OBLIGATORIA.\n\n"
            f"Trabajador/a: {employee_detail}\nEmpleador: {employer_id}\nFecha de terminación consignada: "
            f"{format_date_long_es(effective_date) or 'A completar'}.\nÚltimo día trabajado: "
            f"{format_date_short(optional_date(metadata.get('last_worked_date'))) or 'A completar'}.\n\n"
            f"El cuadro adjunto detalla los haberes consignados por Gs. {format_gs(settlement_gross)}, "
            f"descuentos por Gs. {format_gs(settlement_deduction_total)} y neto referencial por Gs. {format_gs(settlement_net)}.\n\n"
            "Cada rubro debe derivar del cálculo o antecedente correspondiente. Verificar salario pendiente, preaviso, indemnización si procede, vacaciones causadas/proporcionales, aguinaldo, descuentos legalmente admisibles y cualquier régimen especial aplicable antes de su firma o pago."
        ),
    }

    body = bodies[document_type]
    if notes and document_type not in {"certificado_trabajo_b", "constancia", "ficha_empleado", "amonestacion"}:
        body += f"\n\nObservaciones: {notes}"
    elif notes:
        body += f"\n\nObservaciones complementarias: {notes}"
    if document_type in {"contrato_trabajo", "contrato_tiempo_parcial", "contrato_mipymes_plazo_determinado", "contrato_mipymes_80", "adenda_prorroga_contrato", "despido", "amonestacion", "liquidacion_final"}:
        body += "\n\nBORRADOR PARA VALIDACIÓN PROFESIONAL. Revisar todos los datos, la modalidad y el encuadre legal antes de entregar o firmar."
    return title, body


def export_data_from_certificate(certificate: Any) -> ExportData:
    company = certificate.company
    branding = getattr(company, "branding", None)
    metadata = decode_metadata(certificate.observations)
    company_legal_representative = (getattr(company, "legal_representative", "") or "").strip()
    signatory_name = (
        company_legal_representative
        or ((getattr(branding, "signature_name", "") or "").strip() if branding else "")
        or (getattr(company, "responsible_name", "") or "").strip()
    )
    work_certificate = certificate.document_type in {"certificado_trabajo_a", "certificado_trabajo_b", "constancia"}
    configured_signature_title = (getattr(branding, "signature_title", "") or "").strip() if branding else ""
    if company_legal_representative:
        signatory_title = "Representante legal"
    elif work_certificate:
        signatory_title = (
            configured_signature_title
            if configured_signature_title and configured_signature_title.casefold() not in {"representante legal", "representante legal."}
            else "Responsable autorizado"
        )
    else:
        signatory_title = configured_signature_title or ("Responsable" if certificate.document_type == "constancia" else "Representante legal")
    return ExportData(
        document_type=certificate.document_type,
        title=certificate.title,
        city=certificate.city,
        issue_date=certificate.issue_date,
        company_name=certificate.company_name_snapshot,
        company_ruc=getattr(company, "ruc", "") or "",
        company_address=getattr(company, "address", "") or "",
        company_phone=getattr(company, "phone", "") or "",
        company_email=getattr(company, "email", "") or "",
        legal_representative=signatory_name,
        signature_title=signatory_title,
        logo_bytes=prepare_company_logo(
            getattr(branding, "logo_bytes", None) if branding else None,
            fit=getattr(branding, "logo_fit", "contain") if branding else "contain",
            scale=getattr(branding, "logo_scale", 100) if branding else 100,
            alignment=getattr(branding, "logo_alignment", "center") if branding else "center",
            background=getattr(branding, "logo_background", "white") if branding else "white",
        ),
        logo_content_type=getattr(branding, "logo_content_type", "") if branding else "",
        primary_color=getattr(branding, "primary_color", "#173B86") if branding else "#173B86",
        secondary_color=getattr(branding, "secondary_color", "#0B1F48") if branding else "#0B1F48",
        document_footer=getattr(branding, "document_footer", "Generado por Digit Laboral") if branding else "Generado por Digit Laboral",
        employee_name=certificate.employee_name_snapshot,
        employee_document=certificate.employee_document_snapshot,
        position=certificate.position_snapshot,
        admission_date=certificate.admission_date_snapshot,
        salary=certificate.salary_snapshot,
        body=certificate.body,
        status=certificate.status,
        created_by=certificate.created_by,
        created_at=certificate.created_at,
        metadata=metadata,
    )


def safe_download_name(title: str, employee_name: str, suffix: str) -> str:
    raw = f"{title} - {employee_name}".strip(" -")
    cleaned = re.sub(r"[^A-Za-z0-9ÁÉÍÓÚáéíóúÑñÜü ._-]+", "", raw).strip().replace(" ", "_")
    return f"{cleaned[:120] or 'documento_laboral'}.{suffix}"


def _set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def _set_cell_margins(cell, **kwargs: int) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin in ["top", "start", "bottom", "end"]:
        if margin in kwargs:
            node = tc_mar.find(qn(f"w:{margin}"))
            if node is None:
                node = OxmlElement(f"w:{margin}")
                tc_mar.append(node)
            node.set(qn("w:w"), str(kwargs[margin]))
            node.set(qn("w:type"), "dxa")


def _docx_header(document: Document, data: ExportData) -> None:
    """Create a restrained letterhead sized for the normalized horizontal company logo."""
    table = document.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.columns[0].width = Cm(4.0)
    table.columns[1].width = Cm(12.8)
    left, right = table.rows[0].cells
    left.width = Cm(4.0)
    right.width = Cm(12.8)
    left.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    right.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    _set_cell_margins(left, top=150, start=100, bottom=150, end=100)
    _set_cell_margins(right, top=120, start=180, bottom=120, end=120)
    p = left.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if data.logo_bytes:
        _set_cell_shading(left, "F7F9FC")
        try:
            p.add_run().add_picture(io.BytesIO(data.logo_bytes), width=Cm(3.55))
        except Exception:
            _set_cell_shading(left, data.primary_color.lstrip("#") or "173B86")
            r = p.add_run("DL")
            r.bold = True
            r.font.name = "Aptos Display"
            r.font.size = Pt(18)
            r.font.color.rgb = RGBColor(255, 255, 255)
    else:
        _set_cell_shading(left, data.primary_color.lstrip("#") or "173B86")
        r = p.add_run("DL")
        r.bold = True
        r.font.name = "Aptos Display"
        r.font.size = Pt(18)
        r.font.color.rgb = RGBColor(255, 255, 255)

    p = right.paragraphs[0]
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(data.company_name.upper())
    r.bold = True
    r.font.name = "Aptos Display"
    r.font.size = Pt(15.5)
    r.font.color.rgb = RGBColor.from_string(data.primary_color.lstrip("#") or "173B86")
    details = []
    if data.company_ruc:
        details.append(f"RUC {data.company_ruc}")
    if data.company_address:
        details.append(data.company_address)
    if data.company_phone:
        details.append(f"Tel. {data.company_phone}")
    if data.company_email:
        details.append(data.company_email)
    if details:
        p2 = right.add_paragraph(" · ".join(details))
        p2.paragraph_format.space_before = Pt(0)
        p2.paragraph_format.space_after = Pt(0)
        for run in p2.runs:
            run.font.name = "Aptos"
            run.font.size = Pt(8.3)
            run.font.color.rgb = RGBColor(85, 97, 116)

    rule = document.add_paragraph()
    rule.paragraph_format.space_before = Pt(1)
    rule.paragraph_format.space_after = Pt(11)
    rule.paragraph_format.line_spacing = 1
    p_pr = rule._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), (data.primary_color.lstrip("#") or "173B86").upper())
    borders.append(bottom)
    p_pr.append(borders)


BOTH_SIGNATURE_DOCUMENT_TYPES = frozenset({
    "contrato_trabajo", "contrato_tiempo_parcial", "contrato_mipymes_plazo_determinado",
    "contrato_mipymes_80", "adenda_prorroga_contrato", "notificacion_preaviso",
    "despido", "amonestacion", "cambio_salarial", "alta_funcionario", "baja_funcionario",
    "aguinaldo_anual", "aguinaldo_proporcional", "recibo_salario", "liquidacion_final",
    "notificacion_vacaciones", "usufructo_vacaciones", "recibo_vacaciones",
})
EMPLOYEE_SIGNATURE_DOCUMENT_TYPES = frozenset({
    "permiso_paternidad", "renuncia", "solicitud_vacacion", "permiso_laboral",
})
RECEIPT_DATE_DOCUMENT_TYPES = frozenset({
    "notificacion_vacaciones", "baja_funcionario", "alta_funcionario", "cambio_salarial",
})
RECEIPT_DISCLAIMER_DOCUMENT_TYPES = frozenset({
    "notificacion_preaviso", "despido", "amonestacion",
})


def document_signature_mode(document_type: str) -> str:
    """Return the signature layout used consistently by preview, print, Word and PDF."""
    if document_type in BOTH_SIGNATURE_DOCUMENT_TYPES:
        return "both"
    if document_type in EMPLOYEE_SIGNATURE_DOCUMENT_TYPES:
        return "employee"
    return "employer"


def document_receipt_mode(document_type: str) -> str:
    """Return the corresponding receipt/authorization note, if this document requires one."""
    if document_signature_mode(document_type) == "employee":
        return "employee_authorization"
    if document_type in RECEIPT_DISCLAIMER_DOCUMENT_TYPES:
        return "receipt_disclaimer"
    if document_type in RECEIPT_DATE_DOCUMENT_TYPES:
        return "receipt_date"
    return ""


def _requires_both_signatures(document_type: str) -> bool:
    return document_signature_mode(document_type) == "both"


def _requires_employee_signature(document_type: str) -> bool:
    return document_signature_mode(document_type) == "employee"


def _add_document_detail_table_docx(document: Document, data: ExportData) -> None:
    detail = document_detail_table_data(data.document_type, data.metadata, data.salary)
    if not detail:
        return
    heading = document.add_paragraph()
    heading.paragraph_format.space_before = Pt(8)
    heading.paragraph_format.space_after = Pt(5)
    run = heading.add_run(str(detail["title"]))
    run.bold = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor.from_string(data.secondary_color.lstrip("#") or "0B1F48")

    headers = detail["headers"]
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    if len(headers) == 3:
        widths = [Cm(9.2), Cm(3.6), Cm(3.6)]
    else:
        widths = [Cm(5.4), Cm(11.0)]
    for index, label in enumerate(headers):
        cell = table.rows[0].cells[index]
        _set_cell_shading(cell, data.primary_color.lstrip("#") or "173B86")
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        cell.width = widths[index]
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT if index == 0 else WD_ALIGN_PARAGRAPH.RIGHT
        run = paragraph.add_run(str(label))
        run.bold = True
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(255, 255, 255)

    for row_data in detail["rows"]:
        cells_data = row_data["cells"]
        row = table.add_row()
        style = row_data.get("style", "normal")
        if style == "section" and len(headers) == 3:
            cell = row.cells[0].merge(row.cells[-1])
            _set_cell_shading(cell, "EAF0FC")
            cell.text = str(cells_data[0])
            for run in cell.paragraphs[0].runs:
                run.bold = True
                run.font.size = Pt(8)
                run.font.color.rgb = RGBColor.from_string(data.secondary_color.lstrip("#") or "0B1F48")
            continue
        for index, value in enumerate(cells_data):
            cell = row.cells[index]
            cell.width = widths[index]
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if style == "total":
                _set_cell_shading(cell, "F1F4F9")
            elif style == "grand":
                _set_cell_shading(cell, "EAF0FC")
            paragraph = cell.paragraphs[0]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT if index > 0 else WD_ALIGN_PARAGRAPH.LEFT
            run = paragraph.add_run(str(value or ""))
            run.font.size = Pt(8)
            if style in {"total", "grand"}:
                run.bold = True
                if style == "grand":
                    run.font.color.rgb = RGBColor.from_string(data.secondary_color.lstrip("#") or "0B1F48")


def _add_signature_table_docx(document: Document, data: ExportData) -> None:
    document.add_paragraph().paragraph_format.space_after = Pt(10)
    document_type = data.document_type
    if _requires_both_signatures(document_type):
        table = document.add_table(rows=1, cols=2)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        if document_type in {
            "notificacion_preaviso", "despido", "amonestacion", "notificacion_vacaciones",
            "baja_funcionario", "alta_funcionario",
        }:
            labels = ("Firma / recepción del trabajador/a", "Firma del empleador/a")
        elif document_type in {"solicitud_vacacion", "permiso_laboral", "permiso_paternidad"}:
            labels = ("Firma del solicitante", "Autorización de la empresa")
        else:
            labels = ("Firma del trabajador/a", "Firma del empleador/a")
        for idx, label in enumerate(labels):
            cell = table.cell(0, idx)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run("\n\n_______________________________\n")
            r = p.add_run(label)
            r.bold = True
            r.font.size = Pt(8.5)
            if idx == 0 and data.employee_name:
                rr = p.add_run(f"\n{data.employee_name}")
                rr.font.size = Pt(8.5)
                if data.employee_document:
                    p.add_run(f"\nC.I. N.º {data.employee_document}").font.size = Pt(8)
            if idx == 1:
                if data.legal_representative:
                    p.add_run(f"\n{data.legal_representative}").font.size = Pt(8.5)
                if data.signature_title:
                    p.add_run(f"\n{data.signature_title}").font.size = Pt(8)
                p.add_run(f"\n{data.company_name}").font.size = Pt(8)
        receipt_mode = document_receipt_mode(document_type)
        if receipt_mode in {"receipt_date", "receipt_disclaimer"}:
            p = document.add_paragraph("Fecha de recepción: ____/____/________")
            p.paragraph_format.space_before = Pt(10)
            p.runs[0].font.size = Pt(8.5)
            if receipt_mode == "receipt_disclaimer":
                p2 = document.add_paragraph("La firma acredita recepción y no necesariamente conformidad con el contenido.")
                p2.paragraph_format.space_before = Pt(2)
                for run in p2.runs:
                    run.italic = True
                    run.font.size = Pt(8)
    elif _requires_employee_signature(document_type):
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run("\n\n_______________________________\n")
        r = p.add_run(data.employee_name or "Firma del trabajador/a")
        r.bold = True
        if data.employee_document:
            p.add_run(f"\nC.I. N.º {data.employee_document}")
        p2 = document.add_paragraph("RECIBIDO / AUTORIZACIÓN: ____________________    FECHA: ____/____/________")
        p2.paragraph_format.space_before = Pt(12)
        p2.runs[0].font.size = Pt(8.5)
    else:
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(22)
        p.add_run("_______________________________\n")
        if data.document_type in {"certificado_trabajo_a", "certificado_trabajo_b", "constancia"}:
            signatory = (data.legal_representative or "Firma autorizada").strip()
            r = p.add_run(signatory)
            r.bold = True
            p.add_run(f"\n{data.signature_title or 'Responsable autorizado'}")
            p.add_run(f"\n{data.company_name}")
            if data.company_address:
                p.add_run(f"\n{data.company_address}")
            if data.company_phone:
                p.add_run(f"\nTEL. {data.company_phone}")
        else:
            signatory = (data.legal_representative or "Firma autorizada").strip()
            r = p.add_run(signatory)
            r.bold = True
            title_text = data.signature_title or "Representante legal"
            p.add_run(f"\n{title_text}")
            if data.company_name:
                p.add_run(f"\n{data.company_name}")



def build_docx_bytes(data: ExportData) -> bytes:
    document = Document()
    section = document.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(1.6)
    section.bottom_margin = Cm(1.5)
    section.left_margin = Cm(2.1)
    section.right_margin = Cm(2.1)

    styles = document.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"].font.size = Pt(11)
    styles["Normal"].paragraph_format.line_spacing = 1.35

    _docx_header(document, data)

    certificate_model = data.document_type in {"certificado_trabajo_a", "certificado_trabajo_b", "constancia"}
    date_text = f"{data.city.upper()}, {format_date_long_es(data.issue_date)}" if certificate_model else f"{data.city}, {format_date_long_es(data.issue_date)}"
    date_p = document.add_paragraph(date_text)
    date_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    date_p.paragraph_format.space_after = Pt(18)
    date_p.runs[0].font.name = "Aptos"
    date_p.runs[0].font.size = Pt(10.5)

    kicker = document.add_paragraph()
    kicker.alignment = WD_ALIGN_PARAGRAPH.CENTER
    kicker.paragraph_format.space_before = Pt(0)
    kicker.paragraph_format.space_after = Pt(4)
    kicker_run = kicker.add_run("DOCUMENTO LABORAL")
    kicker_run.bold = True
    kicker_run.font.name = "Aptos"
    kicker_run.font.size = Pt(8)
    kicker_run.font.color.rgb = RGBColor.from_string(data.primary_color.lstrip("#") or "173B86")

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(18)
    run = title.add_run(data.title.upper())
    run.bold = True
    run.font.name = "Aptos Display"
    run.font.size = Pt(17)
    run.font.color.rgb = RGBColor.from_string(data.secondary_color.lstrip("#") or "0B1F48")

    meta = data.metadata or {}
    document_number = str(meta.get("document_number") or "").strip()
    if document_number:
        number_p = document.add_paragraph(f"Documento N.º {document_number}")
        number_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        number_p.paragraph_format.space_after = Pt(10)
        number_p.runs[0].font.size = Pt(9)
        number_p.runs[0].italic = True

    for block in data.body.split("\n\n"):
        lines = block.split("\n")
        is_certify_heading = certificate_model and block.strip() == "C E R T I F I C O:"
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER if is_certify_heading else (WD_ALIGN_PARAGRAPH.JUSTIFY if len(lines) == 1 else WD_ALIGN_PARAGRAPH.LEFT)
        p.paragraph_format.space_after = Pt(10 if not is_certify_heading else 14)
        for index, line in enumerate(lines):
            if index:
                p.add_run().add_break()
            run = p.add_run(line)
            run.font.name = "Aptos"
            run.font.size = Pt(12 if is_certify_heading else 11)
            if is_certify_heading:
                run.bold = True
            if line.lower().startswith("ref.:") or line.lower().startswith("ref:"):
                run.bold = True
                run.italic = True

    _add_document_detail_table_docx(document, data)
    _add_signature_table_docx(document, data)

    footer = section.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = fp.add_run(
        f"{data.document_footer} · {format_date_short(data.created_at or datetime.now())} · Estado: {data.status}"
    )
    fr.font.name = "Aptos"
    fr.font.size = Pt(7.5)
    fr.font.color.rgb = RGBColor(120, 130, 145)

    if data.status.lower() == "borrador":
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(12)
        r = p.add_run("BORRADOR - REVISAR ANTES DE FIRMAR")
        r.bold = True
        r.font.size = Pt(8)
        r.font.color.rgb = RGBColor(170, 70, 70)

    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


def _pdf_footer(canvas, doc, data: ExportData) -> None:
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(colors.HexColor(data.primary_color))
    canvas.setLineWidth(0.6)
    canvas.line(21 * mm, 15 * mm, width - 21 * mm, 15 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#7A8597"))
    canvas.drawCentredString(
        width / 2,
        10 * mm,
        f"{data.document_footer} · {format_date_short(data.created_at or datetime.now())} · Estado: {data.status} · Página {doc.page}",
    )
    canvas.restoreState()


def build_pdf_bytes(data: ExportData) -> bytes:
    stream = io.BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=A4,
        rightMargin=21 * mm,
        leftMargin=21 * mm,
        topMargin=17 * mm,
        bottomMargin=20 * mm,
        title=data.title,
        author="Digit Laboral",
    )
    styles = getSampleStyleSheet()
    company_style = ParagraphStyle(
        "Company",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=15.5,
        leading=18,
        textColor=colors.HexColor(data.primary_color),
        spaceAfter=2,
    )
    detail_style = ParagraphStyle(
        "Detail",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.3,
        leading=10,
        textColor=colors.HexColor("#556174"),
    )
    certificate_model = data.document_type in {"certificado_trabajo_a", "certificado_trabajo_b", "constancia"}
    date_style = ParagraphStyle("Date", parent=styles["Normal"], fontName="Helvetica", fontSize=10.5, leading=14, textColor=colors.HexColor("#4E5B70"), alignment=TA_RIGHT, spaceAfter=12)
    certify_style = ParagraphStyle("CertificateACertify", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=12, leading=16, alignment=TA_CENTER, spaceAfter=14)
    kicker_style = ParagraphStyle(
        "DocumentKicker", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=7.5, leading=10, textColor=colors.HexColor(data.primary_color),
        alignment=TA_CENTER, spaceAfter=4,
    )
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=20,
        alignment=TA_CENTER,
        textColor=colors.HexColor(data.secondary_color),
        spaceAfter=16,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=11,
        leading=17,
        alignment=TA_JUSTIFY,
        spaceAfter=11,
    )
    left_style = ParagraphStyle("Left", parent=body_style, alignment=TA_LEFT)
    small_style = ParagraphStyle("Small", parent=styles["Normal"], fontName="Helvetica", fontSize=8.5, leading=11)
    draft_style = ParagraphStyle(
        "Draft",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        textColor=colors.HexColor("#A74646"),
        alignment=TA_CENTER,
        spaceBefore=12,
    )

    story = []
    details = []
    if data.company_ruc:
        details.append(f"RUC {escape(data.company_ruc)}")
    if data.company_address:
        details.append(escape(data.company_address))
    if data.company_phone:
        details.append(f"Tel. {escape(data.company_phone)}")
    if data.company_email:
        details.append(escape(data.company_email))
    logo_cell: Any
    has_logo = False
    if data.logo_bytes:
        try:
            logo_cell = Image(io.BytesIO(data.logo_bytes), width=34 * mm, height=14 * mm, kind="proportional")
            has_logo = True
        except Exception:
            logo_cell = Paragraph("<b>DL</b>", ParagraphStyle("DL", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=18, textColor=colors.white, alignment=TA_CENTER))
    else:
        logo_cell = Paragraph("<b>DL</b>", ParagraphStyle("DL", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=18, textColor=colors.white, alignment=TA_CENTER))
    logo_background = colors.HexColor("#F7F9FC") if has_logo else colors.HexColor(data.primary_color)
    header = Table(
        [[logo_cell, [Paragraph(escape(data.company_name.upper()), company_style), Paragraph(" · ".join(details), detail_style) if details else ""]]],
        colWidths=[38 * mm, 130 * mm],
    )
    header.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), logo_background),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("LINEBELOW", (0, 0), (-1, -1), 1.3, colors.HexColor(data.primary_color)),
            ]
        )
    )
    story.extend([header, Spacer(1, 10 * mm)])
    date_text = f"{data.city.upper()}, {format_date_long_es(data.issue_date)}" if certificate_model else f"{data.city}, {format_date_long_es(data.issue_date)}"
    story.append(Paragraph(escape(date_text), date_style))
    story.append(Paragraph("DOCUMENTO LABORAL", kicker_style))
    story.append(Paragraph(escape(data.title.upper()), title_style))
    document_number = str((data.metadata or {}).get("document_number") or "").strip()
    if document_number:
        story.append(Paragraph(f"Documento N.º {escape(document_number)}", ParagraphStyle("Number", parent=small_style, alignment=TA_RIGHT, spaceAfter=8)))

    for block in data.body.split("\n\n"):
        if certificate_model and block.strip() == "C E R T I F I C O:":
            story.append(Paragraph("C E R T I F I C O:", certify_style))
            continue
        lines = block.split("\n")
        content = "<br/>".join(escape(line) for line in lines)
        story.append(Paragraph(content, left_style if len(lines) > 1 else body_style))

    story.append(Spacer(1, 8 * mm))
    detail = document_detail_table_data(data.document_type, data.metadata, data.salary)
    if detail:
        story.append(Paragraph(escape(str(detail["title"])), ParagraphStyle(
            "DetailHeading", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8.5,
            leading=11, textColor=colors.HexColor(data.secondary_color), spaceBefore=4, spaceAfter=5,
        )))
        table_data = [[Paragraph(f"<b>{escape(str(value))}</b>", small_style) for value in detail["headers"]]]
        for row_data in detail["rows"]:
            cells = [str(value or "") for value in row_data["cells"]]
            style = row_data.get("style", "normal")
            if style == "section":
                row = [Paragraph(f"<b>{escape(cells[0])}</b>", small_style)] + ["" for _ in cells[1:]]
            else:
                row = [Paragraph(escape(value), small_style) for value in cells]
            table_data.append(row)
        col_widths = [95 * mm, 35 * mm, 35 * mm] if len(detail["headers"]) == 3 else [48 * mm, 117 * mm]
        detail_table = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="CENTER")
        commands = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(data.primary_color)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD4E2")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for row_index, row_data in enumerate(detail["rows"], start=1):
            row_style = row_data.get("style", "normal")
            if row_style == "section":
                commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#EAF0FC")))
                if len(detail["headers"]) == 3:
                    commands.append(("SPAN", (0, row_index), (-1, row_index)))
            elif row_style == "total":
                commands.extend([
                    ("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#F1F4F9")),
                    ("FONTNAME", (0, row_index), (-1, row_index), "Helvetica-Bold"),
                ])
            elif row_style == "grand":
                commands.extend([
                    ("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#EAF0FC")),
                    ("FONTNAME", (0, row_index), (-1, row_index), "Helvetica-Bold"),
                    ("TEXTCOLOR", (0, row_index), (-1, row_index), colors.HexColor(data.secondary_color)),
                ])
        detail_table.setStyle(TableStyle(commands))
        story.append(detail_table)
        story.append(Spacer(1, 8 * mm))

    if _requires_both_signatures(data.document_type):
        left = "______________________________<br/><b>Firma / recepción del trabajador/a</b>"
        if data.employee_name:
            left += f"<br/>{escape(data.employee_name)}"
        if data.employee_document:
            left += f"<br/>C.I. N.º {escape(data.employee_document)}"
        right = "______________________________<br/><b>Firma del empleador/a</b>"
        if data.legal_representative:
            right += f"<br/>{escape(data.legal_representative)}"
        if data.signature_title:
            right += f"<br/>{escape(data.signature_title)}"
        right += f"<br/>{escape(data.company_name)}"
        signatures = Table(
            [[Paragraph(left, ParagraphStyle("SigL", parent=small_style, alignment=TA_CENTER)),
              Paragraph(right, ParagraphStyle("SigR", parent=small_style, alignment=TA_CENTER))]],
            colWidths=[83 * mm, 83 * mm],
        )
        signatures.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(signatures)
        receipt_mode = document_receipt_mode(data.document_type)
        if receipt_mode in {"receipt_date", "receipt_disclaimer"}:
            story.append(Spacer(1, 5 * mm))
            story.append(Paragraph("Fecha de recepción: ____/____/________", small_style))
            if receipt_mode == "receipt_disclaimer":
                story.append(Paragraph("La firma acredita recepción y no necesariamente conformidad con el contenido.", small_style))
    elif _requires_employee_signature(data.document_type):
        sig = "______________________________<br/>"
        sig += f"<b>{escape(data.employee_name or 'Firma del trabajador/a')}</b>"
        if data.employee_document:
            sig += f"<br/>C.I. N.º {escape(data.employee_document)}"
        story.append(Paragraph(sig, ParagraphStyle("EmployeeSig", parent=small_style, alignment=TA_CENTER)))
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("RECIBIDO / AUTORIZACIÓN: ____________________    FECHA: ____/____/________", small_style))
    else:
        sig = "______________________________<br/>"
        if data.document_type in {"certificado_trabajo_a", "certificado_trabajo_b", "constancia"}:
            signatory = (data.legal_representative or "Firma autorizada").strip()
            sig += f"<b>{escape(signatory)}</b>"
            sig += f"<br/>{escape(data.signature_title or 'Responsable autorizado')}"
            sig += f"<br/>{escape(data.company_name)}"
            if data.company_address:
                sig += f"<br/>{escape(data.company_address)}"
            if data.company_phone:
                sig += f"<br/>TEL. {escape(data.company_phone)}"
        else:
            signatory = (data.legal_representative or "Firma autorizada").strip()
            sig += f"<b>{escape(signatory)}</b>"
            title_text = data.signature_title or "Representante legal"
            sig += f"<br/>{escape(title_text)}"
            if data.company_name:
                sig += f"<br/>{escape(data.company_name)}"
        story.append(Paragraph(sig, ParagraphStyle("EmployerSig", parent=small_style, alignment=TA_CENTER)))

    if data.status.lower() == "borrador":
        story.append(Paragraph("BORRADOR - REVISAR ANTES DE FIRMAR", draft_style))

    doc.build(story, onFirstPage=lambda c, d: _pdf_footer(c, d, data), onLaterPages=lambda c, d: _pdf_footer(c, d, data))
    return stream.getvalue()
