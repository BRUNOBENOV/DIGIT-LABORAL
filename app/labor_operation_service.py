"""Validated records used by the supplementary labour calculation modules.

The service deliberately separates data validation from HTTP and persistence so the
same rules apply to HTML forms, REST endpoints, and unit tests.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any


OPERATION_TYPES = ("hours", "advance", "discipline", "telegram")
OPERATION_LABELS = {
    "hours": "Carga de horas",
    "advance": "Anticipos",
    "discipline": "Amonestaciones, suspensiones y permisos",
    "telegram": "Telegrama colacionado",
}
OPERATION_STATUSES = {
    "hours": ("Registrado", "Aprobado", "Anulado"),
    "advance": ("Pendiente", "Descontado", "Anulado"),
    "discipline": ("Registrado", "Aprobado", "Anulado"),
    "telegram": ("Borrador", "Listo para imprimir", "Enviado", "Anulado"),
}
DISCIPLINE_TYPES = ("Amonestación", "Suspensión", "Permiso")


def _text(value: Any, field: str, maximum: int, *, required: bool = False) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ValueError(f"{field} es obligatorio.")
    if len(result) > maximum:
        limit_label = f"{maximum:,}".replace(",", ".")
        raise ValueError(f"{field} supera el máximo de {limit_label} caracteres.")
    return result


def _integer(value: Any, field: str, *, minimum: int = 0, maximum: int = 2_000_000_000) -> int:
    if value in (None, ""):
        value = 0
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{field} debe ser un número entero.") from None
    if str(value).strip() not in {str(number), f"+{number}"}:
        raise ValueError(f"{field} debe ser un número entero.")
    if number < minimum or number > maximum:
        raise ValueError(f"{field} debe estar entre {minimum} y {maximum}.")
    return number


def _decimal(value: Any, field: str, *, minimum: float = 0, maximum: float = 24) -> float:
    if value in (None, ""):
        value = 0
    try:
        number = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError(f"{field} debe ser numérico.") from None
    if not (minimum <= number <= maximum):
        raise ValueError(f"{field} debe estar entre {minimum} y {maximum}.")
    return round(number, 2)


def _date(value: Any, field: str, *, required: bool = False) -> date | None:
    if value in (None, ""):
        if required:
            raise ValueError(f"{field} es obligatoria.")
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{field} debe ser una fecha válida (AAAA-MM-DD).") from None


def _common(payload: dict[str, Any]) -> dict[str, Any]:
    operation_type = str(payload.get("operation_type") or "").strip()
    if operation_type not in OPERATION_TYPES:
        raise ValueError("Seleccioná un tipo de operación válido.")
    effective_date = _date(payload.get("effective_date"), "La fecha", required=True)
    end_date = _date(payload.get("end_date"), "La fecha de fin")
    if end_date and effective_date and end_date < effective_date:
        raise ValueError("La fecha de fin no puede ser anterior a la fecha de inicio.")
    notes = _text(payload.get("notes"), "Las observaciones", 3000)
    title = _text(payload.get("title"), "El concepto", 180, required=True)
    status = str(payload.get("status") or OPERATION_STATUSES[operation_type][0]).strip()
    if status not in OPERATION_STATUSES[operation_type]:
        raise ValueError("El estado seleccionado no es válido para este submódulo.")
    return {
        "operation_type": operation_type,
        "title": title,
        "effective_date": effective_date,
        "end_date": end_date,
        "status": status,
        "notes": notes,
    }


def validate_labor_operation(payload: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """Normalize and validate an operation, returning values ready for persistence."""
    if not isinstance(payload, dict):
        raise ValueError("El cuerpo de la operación debe ser un objeto.")
    values = _common(payload)
    kind = values["operation_type"]
    custom: dict[str, Any] = {}
    amount: int | None = None
    quantity: float | None = None
    reference_code = _text(payload.get("reference_code"), "El código de referencia", 50)

    if kind == "hours":
        regular_hours = _decimal(payload.get("regular_hours"), "Las horas ordinarias")
        overtime_hours = _decimal(payload.get("overtime_hours"), "Las horas extraordinarias")
        if regular_hours + overtime_hours <= 0:
            raise ValueError("Registrá al menos una hora trabajada.")
        if regular_hours + overtime_hours > 24:
            raise ValueError("El total diario no puede superar 24 horas.")
        salary = _integer(payload.get("salary_reference"), "El salario mensual de referencia")
        monthly_hours = _decimal(payload.get("monthly_hours") or 240, "Las horas mensuales de referencia", minimum=1, maximum=400)
        multiplier = _decimal(payload.get("multiplier") or 1.5, "El multiplicador de recargo", minimum=1, maximum=3)
        hourly_value = salary / monthly_hours
        estimated_amount = round(hourly_value * (regular_hours + overtime_hours * multiplier)) if salary else 0
        amount = estimated_amount
        quantity = regular_hours + overtime_hours
        custom = {
            "regular_hours": regular_hours,
            "overtime_hours": overtime_hours,
            "salary_reference": salary,
            "monthly_hours": monthly_hours,
            "multiplier": multiplier,
            "hourly_value": round(hourly_value),
            "calculation_note": "Estimación orientativa; revisar jornada, franja horaria y recargo legal aplicable.",
        }
        values["title"] = values["title"] or "Registro de jornada"

    elif kind == "advance":
        amount = _integer(payload.get("amount"), "El importe del anticipo", minimum=1)
        custom = {
            "deduction_period": _text(payload.get("deduction_period"), "El periodo de descuento", 7),
            "payment_method": _text(payload.get("payment_method"), "El medio de entrega", 60),
        }

    elif kind == "discipline":
        subtype = _text(payload.get("subtype"), "El tipo de novedad", 40, required=True)
        if subtype not in DISCIPLINE_TYPES:
            raise ValueError("El tipo debe ser Amonestación, Suspensión o Permiso.")
        if subtype in {"Suspensión", "Permiso"} and not values["end_date"]:
            raise ValueError("La fecha de fin es obligatoria para suspensiones y permisos.")
        quantity_raw = payload.get("quantity")
        quantity = _decimal(quantity_raw, "La cantidad", maximum=24) if quantity_raw not in (None, "") else None
        amount = None
        custom = {
            "subtype": subtype,
            "reason": _text(payload.get("reason"), "El motivo", 1000, required=True),
            "authorized_by": _text(payload.get("authorized_by"), "La persona autorizante", 180),
            "quantity": quantity,
        }

    elif kind == "telegram":
        amount = None
        custom = {
            "recipient": _text(payload.get("recipient"), "El destinatario", 180, required=True),
            "recipient_document": _text(payload.get("recipient_document"), "El documento del destinatario", 40),
            "recipient_address": _text(payload.get("recipient_address"), "El domicilio del destinatario", 300, required=True),
            "sender": _text(payload.get("sender"), "El remitente", 180, required=True),
            "body": _text(payload.get("body"), "El texto del telegrama", 7000, required=True),
            "legal_review": _text(payload.get("legal_review"), "La referencia de revisión", 500),
            "calculated_at": (today or date.today()).isoformat(),
        }

    return {
        **values,
        "reference_code": reference_code,
        "quantity": quantity,
        "amount": amount,
        "payload": custom,
        "payload_json": json.dumps(custom, ensure_ascii=False, separators=(",", ":")),
    }


def operation_to_dict(item: Any) -> dict[str, Any]:
    """Serialize a persisted model into a stable REST representation."""
    try:
        payload = json.loads(item.payload_json or "{}")
    except (TypeError, ValueError):
        payload = {}
    return {
        "id": item.id,
        "company_id": item.company_id,
        "employee_id": item.employee_id,
        "operation_type": item.operation_type,
        "reference_code": item.reference_code or "",
        "title": item.title,
        "effective_date": item.effective_date.isoformat(),
        "end_date": item.end_date.isoformat() if item.end_date else None,
        "quantity": float(item.quantity) if item.quantity is not None else None,
        "amount": item.amount,
        "status": item.status,
        "notes": item.notes or "",
        "payload": payload,
        "created_by": item.created_by or "",
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }
