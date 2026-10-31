"""Defaults for the new settlement form, without confirming legal facts."""
from decimal import Decimal, InvalidOperation


def settlement_defaults(values):
    data = dict(values)
    if data.get("kind") != "settlement" or str(data.get("settlement_preset_version", "")) != "1":
        return data
    data["severance_regime"] = data.get("severance_regime") or "ordinary"
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
