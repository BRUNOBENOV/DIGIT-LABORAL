"""Defaults for the new settlement form, without confirming legal facts."""
from decimal import Decimal, InvalidOperation
from calendar import monthrange
from datetime import date


def service_years(values):
    """Completed anniversaries, including Feb 29 → Feb 28 in non-leap years."""
    try:
        start, end = (date.fromisoformat(str(values.get(key, ""))) for key in ("start_date", "end_date"))
        if end < start or not 1900 <= start.year <= end.year <= 2100:
            return None
        years = end.year - start.year
        anniversary = start.replace(year=end.year, day=min(start.day, monthrange(end.year, start.month)[1]))
        return years - int(end < anniversary)
    except (ValueError, TypeError):
        return None


def settlement_defaults(values):
    data = dict(values)
    version = str(data.get("settlement_preset_version", ""))
    if data.get("kind") != "settlement" or version not in {"1", "2"}:
        return data
    data["severance_regime"] = data.get("severance_regime") or "ordinary"
    if version == "2":
        years = service_years(data)
        eligible = (data.get("reason") == "dismissal" and years is not None and years >= 10
                    and str(data.get("indefinite", "")).lower() in {"on", "true", "1", "yes"}
                    and str(data.get("trial_completed", "")).lower() in {"on", "true", "1", "yes"}
                    and str(data.get("protected", "")).lower() not in {"on", "true", "1", "yes"})
        if data["severance_regime"] == "ordinary" and years is not None and years >= 10 and data.get("reason") == "dismissal":
            data["severance_regime"] = "stability_double" if eligible else "auto"
        if data.get("reason") != "justified":
            for key in ("judicial_confirmed", "judicial_date", "judicial_reference", "judicial_document_id", "judicial_document_sha256"):
                data[key] = ""
    if not str(data.get("notice_served", "")).strip():
        data["notice_served"] = "0"
    if data.get("reason") in {"resignation", "justified"}:
        data["notice_served"] = "0"
        data["average_origin"] = "manual"
        data.pop("average_payroll_fingerprint", None)
        data["average_payroll_reviewed"] = ""
        data["average_from_salary"] = ""
    elif (not str(data.get("average_salary", "")).strip()
          and data.get("average_origin") != "payroll"
          and data.get("average_from_salary", "on") == "on"
          and str(data.get("pay_basis") or "monthly") != "daily"
          and str(data.get("salary", "")).strip()):
        data["average_salary"] = str(data["salary"]).strip()
        data["average_from_salary"] = "on"
    if data.get("average_from_salary") == "on":
        try:
            matches = Decimal(str(data.get("average_salary", ""))) == Decimal(str(data.get("salary", "")))
        except InvalidOperation:
            matches = False
        if not matches or data.get("average_origin") == "payroll":
            data["average_from_salary"] = ""
    if data["severance_regime"] != "stability_double":
        for key in ("stability_basis", "stability_evidence", "stability_confirmed"):
            data[key] = ""
    return data
