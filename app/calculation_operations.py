from __future__ import annotations

import re
import secrets
from datetime import date

ADVANCE_STATUSES = ("Registrado", "Descontado", "Anulado")
LABOR_ACTION_TYPES = ("Amonestación", "Suspensión", "Permiso")
LABOR_ACTION_STATUSES = ("Registrado", "Aprobado", "Rechazado", "Cumplido")
TELEGRAM_TYPES = ("Intimación", "Preaviso", "Apercibimiento", "Comunicación", "Otro")
TELEGRAM_STATUSES = ("Borrador", "Revisado", "Emitido", "Enviado", "Anulado")
_PERIOD_RE = re.compile(r"^\\d{4}-(0[1-9]|1[0-2])$")
_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{0,39}$")


def parse_iso_date(value: str | date | None, field_label: str, *, required: bool = True) -> date | None:
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        if required:
            raise ValueError(f"{field_label} es obligatorio.")
        return None
    try:
        parsed = date.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_label} debe ser una fecha válida (AAAA-MM-DD).") from exc
    if parsed.isoformat() != raw:
        raise ValueError(f"{field_label} debe ser una fecha válida (AAAA-MM-DD).")
    return parsed


def validate_advance(*, amount: int | str, advance_date: str | date, salary_period: str, status: str = "Registrado", notes: str = "") -> dict:
    try:
        amount_value = int(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("El importe del anticipo debe ser un número entero en guaraníes.") from exc
    if amount_value <= 0 or amount_value > 2_147_483_647:
        raise ValueError("El importe del anticipo debe ser mayor que cero.")
    period = str(salary_period or "").strip()
    if not _PERIOD_RE.fullmatch(period):
        raise ValueError("El período salarial debe estar en formato AAAA-MM.")
    normalized_status = str(status or "").strip()
    if normalized_status not in ADVANCE_STATUSES:
        raise ValueError("El estado del anticipo no es válido.")
    notes_value = str(notes or "").strip()
    if len(notes_value) > 2000:
        raise ValueError("Las observaciones no pueden superar los 2.000 caracteres.")
    return {"amount": amount_value, "advance_date": parse_iso_date(advance_date, "La fecha del anticipo"),
            "salary_period": period, "status": normalized_status, "notes": notes_value}


def validate_labor_action(
    *, action_type: str, action_date: str | date, start_date: str | date | None = None,
    end_date: str | date | None = None, reason: str, details: str = "", status: str = "Registrado",
) -> dict:
    kind = str(action_type or "").strip()
    if kind not in LABOR_ACTION_TYPES:
        raise ValueError("El tipo de movimiento laboral no es válido.")
    state = str(status or "").strip()
    if state not in LABOR_ACTION_STATUSES:
        raise ValueError("El estado del movimiento laboral no es válido.")
    when = parse_iso_date(action_date, "La fecha de registro")
    start = parse_iso_date(start_date, "La fecha inicial", required=False)
    end = parse_iso_date(end_date, "La fecha final", required=False)
    if start and end and end < start:
        raise ValueError("La fecha final no puede ser anterior a la fecha inicial.")
    reason_value = str(reason or "").strip()
    detail_value = str(details or "").strip()
    if not reason_value:
        raise ValueError("El motivo es obligatorio.")
    if len(reason_value) > 240:
        raise ValueError("El motivo no puede superar los 240 caracteres.")
    if len(detail_value) > 4000:
        raise ValueError("El detalle no puede superar los 4.000 caracteres.")
    if kind == "Suspensión" and (not start or not end):
        raise ValueError("La suspensión requiere fecha inicial y final.")
    if kind == "Permiso" and start and not end:
        raise ValueError("Ingresá la fecha final del permiso.")
    return {"action_type": kind, "action_date": when, "start_date": start, "end_date": end,
            "reason": reason_value, "details": detail_value, "status": state}


def generate_telegram_code(company_id: int, issue_date: date, token: str | None = None) -> str:
    suffix = (token or secrets.token_hex(3)).upper()
    return f"TC-{company_id:04d}-{issue_date:%Y%m%d}-{suffix}"[:40]


def validate_telegram(
    *, company_id: int, telegram_code: str = "", telegram_type: str, issue_date: str | date,
    destination_address: str = "", subject: str, body: str, status: str = "Borrador", notes: str = "",
) -> dict:
    kind = str(telegram_type or "").strip()
    if kind not in TELEGRAM_TYPES:
        raise ValueError("El tipo de telegrama no es válido.")
    state = str(status or "").strip()
    if state not in TELEGRAM_STATUSES:
        raise ValueError("El estado del telegrama no es válido.")
    when = parse_iso_date(issue_date, "La fecha del telegrama")
    code = str(telegram_code or "").strip().upper()
    if code and not _CODE_RE.fullmatch(code):
        raise ValueError("El código del telegrama contiene caracteres no permitidos.")
    if not code:
        code = generate_telegram_code(company_id, when)
    address = str(destination_address or "").strip()
    subject_value = str(subject or "").strip()
    body_value = str(body or "").strip()
    notes_value = str(notes or "").strip()
    if not address:
        raise ValueError("El domicilio de destino es obligatorio.")
    if len(address) > 300:
        raise ValueError("El domicilio no puede superar los 300 caracteres.")
    if not subject_value or len(subject_value) > 200:
        raise ValueError("El asunto es obligatorio y no puede superar los 200 caracteres.")
    if not body_value:
        raise ValueError("El contenido del telegrama es obligatorio.")
    if len(body_value) > 8000:
        raise ValueError("El contenido no puede superar los 8.000 caracteres.")
    if len(notes_value) > 2000:
        raise ValueError("Las observaciones no pueden superar los 2.000 caracteres.")
    return {"telegram_code": code, "telegram_type": kind, "issue_date": when,
            "destination_address": address, "subject": subject_value, "body": body_value,
            "status": state, "notes": notes_value}


WORK_HOURS_STATUSES = ("Registrada", "Incorporada a nómina", "Anulada")


def _decimal_hours(value: str | int | float, label: str):
    from decimal import Decimal, InvalidOperation

    try:
        number = Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} debe ser un número válido.") from exc
    if not number.is_finite() or number < 0 or number > 24:
        raise ValueError(f"{label} debe estar entre 0 y 24 horas.")
    return number.quantize(Decimal("0.01"))


def validate_work_hours(
    *, work_date: str | date, ordinary_hours: str | int | float = 0,
    overtime_hours: str | int | float = 0, night_hours: str | int | float = 0,
    holiday_hours: str | int | float = 0, status: str = "Registrada", notes: str = "",
) -> dict:
    when = parse_iso_date(work_date, "La fecha trabajada")
    buckets = {
        "ordinary_hours": _decimal_hours(ordinary_hours, "Las horas ordinarias"),
        "overtime_hours": _decimal_hours(overtime_hours, "Las horas extraordinarias"),
        "night_hours": _decimal_hours(night_hours, "Las horas nocturnas"),
        "holiday_hours": _decimal_hours(holiday_hours, "Las horas en feriado/descanso"),
    }
    total = sum(buckets.values())
    if total > 24:
        raise ValueError("La suma de horas por día no puede superar 24.")
    normalized_status = str(status or "").strip()
    if normalized_status not in WORK_HOURS_STATUSES:
        raise ValueError("El estado de la carga horaria no es válido.")
    notes_value = str(notes or "").strip()
    if len(notes_value) > 2000:
        raise ValueError("Las observaciones no pueden superar los 2.000 caracteres.")
    return {"work_date": when, "work_period": when.strftime("%Y-%m"), **buckets,
            "status": normalized_status, "notes": notes_value}


SETTLEMENT_REASONS = ("Renuncia", "Despido con causa", "Despido sin causa", "Fin de contrato", "Mutuo acuerdo", "Otro")
SETTLEMENT_AMOUNT_FIELDS = ("pending_salary", "vacation_pay", "aguinaldo_prorated", "notice_pay", "severance_pay", "other_income", "discounts")


def validate_settlement(*, termination_date: str | date, termination_reason: str, amounts: dict, notes: str = "") -> dict:
    """Validate a termination settlement proposal without deciding legal entitlement."""
    when = parse_iso_date(termination_date, "La fecha de terminación")
    reason = str(termination_reason or "").strip()
    if reason not in SETTLEMENT_REASONS:
        raise ValueError("Seleccioná una causa de terminación válida.")
    normalized_amounts = {}
    for field in SETTLEMENT_AMOUNT_FIELDS:
        raw = amounts.get(field, 0)
        try:
            value = int(raw or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"El rubro {field} debe ser un importe entero en guaraníes.") from exc
        if value < 0 or value > 2_147_483_647:
            raise ValueError(f"El rubro {field} debe estar entre 0 y 2.147.483.647 guaraníes.")
        normalized_amounts[field] = value
    total_entitlements = sum(normalized_amounts[key] for key in SETTLEMENT_AMOUNT_FIELDS if key != "discounts")
    net = total_entitlements - normalized_amounts["discounts"]
    if total_entitlements > 2_147_483_647:
        raise ValueError("La suma de los rubros supera el máximo admitido; revisá los importes.")
    notes_value = str(notes or "").strip()
    if len(notes_value) > 4000:
        raise ValueError("Las observaciones no pueden superar los 4.000 caracteres.")
    return {
        "termination_date": when,
        "termination_reason": reason,
        **normalized_amounts,
        "total_entitlements": total_entitlements,
        "net_amount": net,
        "notes": notes_value,
        "review_required": True,
    }


VACATION_STATUSES = ("Pendiente", "Aprobada", "Completada")
AGUINALDO_STATUSES = ("Borrador", "Revisar", "Aprobado", "Pagado", "Anulado")


def validate_vacation_record(*, period_year: int | str, entitled_days: int | str, used_days: int | str = 0,
                             start_date: str | date | None = None, end_date: str | date | None = None,
                             status: str = "Pendiente", notes: str = "", today: date | None = None) -> dict:
    current = today or date.today()
    try:
        year = int(period_year)
        entitled = int(entitled_days)
        used = int(used_days or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("El año, los días reconocidos y los días utilizados deben ser numéricos.") from exc
    if year < 1900 or year > current.year:
        raise ValueError("El año del período de vacaciones debe estar entre 1900 y el año actual.")
    if not 0 <= entitled <= 365 or not 0 <= used <= 365:
        raise ValueError("Los días de vacaciones deben estar entre 0 y 365.")
    if used > entitled:
        raise ValueError("Los días utilizados no pueden superar los días reconocidos del período.")
    start = parse_iso_date(start_date, "La fecha inicial", required=False)
    end = parse_iso_date(end_date, "La fecha final", required=False)
    if bool(start) != bool(end):
        raise ValueError("Ingresá ambas fechas del período de vacaciones o dejá ambas vacías.")
    if start and end and end < start:
        raise ValueError("La fecha final no puede ser anterior a la fecha inicial.")
    normalized_status = str(status or "").strip()
    if normalized_status not in VACATION_STATUSES:
        raise ValueError("El estado de vacaciones no es válido.")
    note = str(notes or "").strip()
    if len(note) > 2000:
        raise ValueError("Las observaciones no pueden superar los 2.000 caracteres.")
    return {"period_year": year, "entitled_days": entitled, "used_days": used, "start_date": start, "end_date": end,
            "status": normalized_status, "notes": note}


def validate_aguinaldo_record(*, year: int | str, total_remunerations: int | str, status: str = "Borrador",
                              notes: str = "", today: date | None = None) -> dict:
    current = today or date.today()
    try:
        year_value = int(year)
        remuneration_value = int(total_remunerations)
    except (TypeError, ValueError) as exc:
        raise ValueError("El año y las remuneraciones totales deben ser números enteros.") from exc
    if year_value < 1900 or year_value > current.year:
        raise ValueError("El año del aguinaldo debe estar entre 1900 y el año actual.")
    if remuneration_value < 0 or remuneration_value > 2_147_483_647:
        raise ValueError("Las remuneraciones computables deben estar entre 0 y 2.147.483.647 guaraníes.")
    normalized_status = str(status or "").strip()
    if normalized_status not in AGUINALDO_STATUSES:
        raise ValueError("El estado del aguinaldo no es válido.")
    note = str(notes or "").strip()
    if len(note) > 2000:
        raise ValueError("Las observaciones no pueden superar los 2.000 caracteres.")
    return {"year": year_value, "total_remunerations": remuneration_value,
            "calculated_amount": (remuneration_value + 6) // 12,
            "status": normalized_status, "notes": note}
