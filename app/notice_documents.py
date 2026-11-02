"""Date suggestions for a notice letter, separate from payroll calculations."""
from datetime import date, timedelta
from math import isfinite


def saved_notice_dates(inputs: dict) -> dict[str, str]:
    def valid(raw) -> str:
        try:
            return date.fromisoformat(str(raw or "").strip()).isoformat()
        except ValueError:
            return ""
    return {
        "notice_start_date": valid(inputs.get("notice_start_date")),
        "effective_date": valid(inputs.get("effective_date")) or valid(inputs.get("notice_end_date")),
    }


def notice_date_defaults(inputs: dict, issued_on: date, days: float) -> dict[str, str]:
    values = saved_notice_dates(inputs)
    start = date.fromisoformat(values["notice_start_date"]) if values["notice_start_date"] else issued_on
    end = values["effective_date"]
    if not end and isfinite(days) and days > 0 and days == int(days):
        try:
            end = (start + timedelta(days=int(days))).isoformat()
        except OverflowError:
            end = ""
    return {"notice_start_date": start.isoformat(), "effective_date": end,
            "date_source": "Cálculo guardado" if values["effective_date"] else "Propuesta desde la fecha de inicio y el plazo guardado"}


def is_notice_letter(document_type: str, metadata: dict | None) -> bool:
    return document_type == "notificacion_preaviso" and str((metadata or {}).get("notice_template_version", "")) == "1"
