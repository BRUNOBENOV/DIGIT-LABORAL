"""Selección salarial y asistencia compartidas; nunca recalcula importes."""
from __future__ import annotations

import hashlib
import json
import re

from sqlalchemy import select

from .models import CalculationRecord, IntegrationBatch, SalaryImportDetail

SALARY_TYPES = ("salary", "suite_salary")
APPROVED = {"Aprobado", "Validado"}
PENDING = {"Borrador", "Revisar", "En Revisión"}
ATTENDANCE_FIELDS = ("days_worked", "hours_worked", "payment_method", "period_start", "period_end")


def object_json(raw):
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def select_salary_versions(rows):
    """Rows arrive newest first. Drafts do not replace approval; annulments do."""
    latest, decided = {}, {}
    for row in rows:
        if row.employee_id is None:
            continue
        latest.setdefault(row.employee_id, row)
        if row.status not in PENDING:
            decided.setdefault(row.employee_id, row)
    return {eid: decided.get(eid, row) for eid, row in latest.items()}


def salary_query(company_id, period, employee_id=None):
    query = select(CalculationRecord).where(
        CalculationRecord.company_id == company_id,
        CalculationRecord.reference_period == period,
        CalculationRecord.calculation_type.in_(SALARY_TYPES),
    )
    if employee_id is not None:
        query = query.where(CalculationRecord.employee_id == employee_id)
    return query.order_by(CalculationRecord.created_at.desc(), CalculationRecord.id.desc())


def approved_salary(db, company_id, employee_id, period):
    row = select_salary_versions(db.scalars(salary_query(company_id, period, employee_id))).get(employee_id)
    return row if row and row.status in APPROVED else None


def calculation_fingerprint(item):
    return hashlib.sha256((item.input_json or "{}").encode() + b"\\n" + (item.result_json or "{}").encode()).hexdigest()


def merge_attendance(inputs, batch, detail, item):
    values = dict(inputs)
    result = object_json(item.result_json)
    origins = {}
    for key in ATTENDANCE_FIELDS:
        if values.get(key) in (None, ""):
            alias = {"days_worked": "worked_days", "hours_worked": "worked_hours"}.get(key)
            candidate = result.get(key, inputs.get(alias) if alias else None)
            if candidate not in (None, ""):
                values[key] = candidate
        if values.get(key) not in (None, ""):
            origins[key] = "Cálculo guardado"
    if batch and batch.status in {"Validado", "Presentado", "Aceptado"}:
        additional = object_json(batch.payload_json)
        communication_hash = hashlib.sha256((item.input_json or "{}").encode() + b"\n" + (item.result_json or "{}").encode()).hexdigest()
        if additional.get("source_snapshot_sha256") in {calculation_fingerprint(item), communication_hash}:
            for key in ATTENDANCE_FIELDS:
                if additional.get(key) not in (None, ""):
                    values[key], origins[key] = additional[key], "Comunicación validada"
    if detail and detail.source_sha256 == calculation_fingerprint(item):
        for key in ATTENDANCE_FIELDS:
            candidate = getattr(detail, key, None)
            if candidate not in (None, ""):
                values[key] = candidate.isoformat() if hasattr(candidate, "isoformat") else str(candidate)
                origins[key] = "Anexo de asistencia revisado"
    values["attendance_origins"] = origins
    return values


def attendance_data(db, item):
    detail = db.scalar(select(SalaryImportDetail).where(
        SalaryImportDetail.company_id == item.company_id,
        SalaryImportDetail.calculation_record_id == item.id,
    ))
    batch = db.scalar(select(IntegrationBatch).where(
        IntegrationBatch.company_id == item.company_id,
        IntegrationBatch.calculation_record_id == item.id,
        IntegrationBatch.authority == "REOP",
        IntegrationBatch.batch_type == "Liquidación salarial individual",
        IntegrationBatch.status.in_(["Validado", "Presentado", "Aceptado"]),
    ).order_by(IntegrationBatch.created_at.desc(), IntegrationBatch.id.desc()).limit(1))
    return merge_attendance(object_json(item.input_json), batch, detail, item)


def attendance_proposal(db, company_id, employee_id, period):
    period = str(period or "")
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", period or ""):
        raise ValueError("Seleccioná un mes válido para cargar la asistencia.")
    item = approved_salary(db, company_id, employee_id, period)
    if not item:
        return {"available": False, "period": period, "calculation_id": None, "values": {}, "fingerprint": ""}
    resolved = attendance_data(db, item)
    values = {key: str(resolved.get(key) if resolved.get(key) is not None else "") for key in ATTENDANCE_FIELDS}
    signature = hashlib.sha256(json.dumps([item.id, calculation_fingerprint(item), values], sort_keys=True).encode()).hexdigest()
    return {"available": True, "period": period, "calculation_id": item.id, "values": values,
            "fingerprint": signature, "origins": resolved["attendance_origins"]}


def apply_attendance_proposal(data, proposal):
    data["attendance_source_id"] = str(proposal["calculation_id"] or "")
    data["attendance_source_sha256"] = proposal["fingerprint"]
    for key in ATTENDANCE_FIELDS:
        if proposal["values"].get(key) not in (None, ""):
            data[key] = proposal["values"][key]


def verify_attendance_inheritance(db, employee, data):
    from .labor_calculator import CalculationError
    if data.get("kind") != "salary" or not employee or not data.get("attendance_source_id"):
        return
    try:
        proposal = attendance_proposal(db, employee.company_id, employee.id, data.get("month", ""))
    except ValueError as exc:
        raise CalculationError(str(exc), "month") from None
    if (str(proposal["calculation_id"] or "") != str(data["attendance_source_id"])
            or proposal["fingerprint"] != data.get("attendance_source_sha256")):
        raise CalculationError("El cálculo de origen o su asistencia cambió. Volvé a cargar la selección antes de guardar.", "days_worked")
    if data.get("attendance_override") != "on":
        apply_attendance_proposal(data, proposal)
    else:
        # Omitted fields are not an instruction to erase inherited metadata.
        for key in ATTENDANCE_FIELDS:
            if key not in data and proposal["values"].get(key) not in (None, ""):
                data[key] = proposal["values"][key]
