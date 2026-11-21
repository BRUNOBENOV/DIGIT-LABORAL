"""Presentation of the reviewed export and recovery of an existing salary batch."""
from __future__ import annotations

import re

from .official_salary_import import REOP_PAYMENT_LABELS
from .reop_ledger import gross_income


def group_import_errors(errors: list[str], company_id: int) -> list[dict]:
    groups: dict[str, dict] = {}
    for error in errors:
        match = re.match(r"(.+?) \((?:legajo [^)]+|cálculo #\d+)\): (.+)", error)
        reason = match[2] if match else error
        if reason.rstrip(".") in {"seleccioná la forma de pago real para este trabajador",
                                  "falta una forma de pago reconocida en el salario guardado"}:
            reason = "Falta indicar la forma de pago."
        group = groups.setdefault(reason, {"message": reason, "workers": [], "action": "", "url": ""})
        if match and match[1] not in group["workers"]:
            group["workers"].append(match[1])
        if "patronal" in reason.casefold():
            group.update(action="Completar patronal", url=f"/app/companies/{company_id}?open=editCompanyModal")
        elif "forma de pago" in reason.casefold():
            group.update(action="Revisar formas de pago", url="#pagos-reop")
        elif any(word in reason.casefold() for word in ("horas", "jornadas", "fechas del período")):
            group.update(action="Revisar asistencia", url="#asistencia-exportacion")
    return list(groups.values())


def reviewed_workers(rows: list[list], employees: list, errors: list[str], authority: str) -> list[dict]:
    by_document = {str(employee.document_number).strip(): employee for employee in employees}
    workers = []
    for row in rows:
        document = str(row[1] if authority == "REOP" else row[2])
        employee = by_document.get(document)
        name = employee.full_name if employee else document
        warnings = [error for error in errors if error.startswith(name + " (")]
        salary = row[9] if authority == "REOP" else row[10]
        # Vista previa REOP: el salario básico es solo una de las 15 columnas
        # de ingresos (índices 9..23). Mostrar el total bruto que realmente
        # resulta del Excel, sin cambiar las columnas del archivo oficial.
        total_income = gross_income(row) if authority == "REOP" else None
        workers.append({
            "name": name, "document": document,
            "code": employee.employee_code if employee else None,
            "employee_id": employee.id if employee else None,
            "salary": salary,
            "total_income": total_income,
            "additional_income": (
                total_income - salary
                if total_income is not None and type(salary) is int else None
            ),
            "days": row[5] if authority == "REOP" else row[6],
            "hours": row[7] if authority == "REOP" else None,
            "payment": REOP_PAYMENT_LABELS.get(str(row[4]), "Pendiente") if authority == "REOP" else "",
            "warnings": warnings,
        })
    return workers


def checked_progress(value: dict, rows: int) -> dict:
    phase = value.get("phase")
    if phase in {"attached", "validation-requested"}:
        return {"phase": phase, "rows": rows}
    if phase not in {"processing", "corrections", "prevalidated", "imported"}:
        raise ValueError("Estado de REOP inválido.")
    counts = [value.get(key) for key in ("valid", "errors", "imported")]
    if any(type(count) is not int or not 0 <= count <= rows for count in counts):
        raise ValueError("Conteos de REOP inválidos.")
    valid, errors, imported = counts
    if valid + errors > rows or imported > valid:
        raise ValueError("Conteos de REOP inconsistentes.")
    if (phase == "prevalidated" and (valid != rows or errors)) or (phase == "imported" and imported != rows):
        raise ValueError("El lote todavía está incompleto.")
    result = dict(phase=phase, rows=rows, valid=valid, errors=errors, imported=imported)
    if phase == "processing" and value.get("step") in {"validation-queued", "validating", "import-queued", "importing"}:
        result["step"] = value["step"]
        ahead = value.get("jobsAhead")
        if result["step"].endswith("-queued") and type(ahead) is int and 0 <= ahead <= 100000:
            result["jobsAhead"] = ahead
    return result
