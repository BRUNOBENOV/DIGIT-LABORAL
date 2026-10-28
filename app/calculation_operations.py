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
