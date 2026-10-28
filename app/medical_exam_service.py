from __future__ import annotations

import re
import secrets
from datetime import date, timedelta
from typing import Any

MEDICAL_EXAM_TYPES = ("Ingreso", "Periódico", "Salida", "Especial")
MEDICAL_EXAM_RESULTS = ("Apto", "No apto", "Observaciones")
MEDICAL_EXAM_WARNING_DAYS = 30
_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{0,39}$")


def parse_medical_exam_date(value: str | date | None, label: str, *, today: date | None = None) -> date:
    """Parse an ISO date and reject missing, impossible, or future exam dates."""
    current_day = today or date.today()
    if isinstance(value, date):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"La {label} es obligatoria.")
        try:
            parsed = date.fromisoformat(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"La {label} debe ser una fecha válida en formato AAAA-MM-DD.") from exc
        if parsed.isoformat() != raw:
            raise ValueError(f"La {label} debe ser una fecha válida en formato AAAA-MM-DD.")
    if label.lower() in {"fecha del examen", "fecha de examen"} and parsed > current_day:
        raise ValueError("La fecha del examen no puede ser futura.")
    return parsed


def generate_medical_exam_code(company_id: int, exam_date: date, *, token: str | None = None) -> str:
    """Generate a readable company-scoped code while keeping concurrent inserts unlikely to collide."""
    suffix = (token or secrets.token_hex(3)).upper()
    code = f"EM-{company_id:04d}-{exam_date:%Y%m%d}-{suffix}"
    return code[:40]


def validate_medical_exam_fields(
    *,
    company_id: int,
    exam_code: str | None,
    exam_type: str,
    exam_date_raw: str | date | None,
    result: str,
    expires_on_raw: str | date | None,
    observations: str | None,
    today: date | None = None,
) -> dict[str, Any]:
    """Validate and normalize form values before persistence."""
    current_day = today or date.today()
    normalized_type = str(exam_type or "").strip()
    if normalized_type not in MEDICAL_EXAM_TYPES:
        raise ValueError("Seleccioná un tipo de examen válido.")

    normalized_result = str(result or "").strip()
    if normalized_result not in MEDICAL_EXAM_RESULTS:
        raise ValueError("Seleccioná un resultado válido.")

    exam_date = parse_medical_exam_date(exam_date_raw, "fecha del examen", today=current_day)
    expires_on = parse_medical_exam_date(expires_on_raw, "fecha de vigencia o vencimiento", today=current_day)
    if expires_on < exam_date:
        raise ValueError("La fecha de vigencia o vencimiento no puede ser anterior a la fecha del examen.")

    normalized_code = str(exam_code or "").strip().upper()
    if normalized_code and not _CODE_RE.fullmatch(normalized_code):
        raise ValueError("El código solo puede contener letras, números, punto, guion, barra o guion bajo (máximo 40 caracteres).")
    if not normalized_code:
        normalized_code = generate_medical_exam_code(company_id, exam_date)

    notes = str(observations or "").strip()
    if len(notes) > 3000:
        raise ValueError("Las observaciones no pueden superar los 3.000 caracteres.")

    return {
        "exam_code": normalized_code,
        "exam_type": normalized_type,
        "exam_date": exam_date,
        "result": normalized_result,
        "expires_on": expires_on,
        "observations": notes,
    }


def medical_exam_expiry_state(
    expires_on: date,
    *,
    today: date | None = None,
    warning_days: int = MEDICAL_EXAM_WARNING_DAYS,
) -> str:
    current_day = today or date.today()
    if expires_on < current_day:
        return "Vencido"
    if expires_on <= current_day + timedelta(days=warning_days):
        return "Por vencer"
    return "Vigente"
