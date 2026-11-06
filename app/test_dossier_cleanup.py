"""Transactional purge of explicitly synthetic employee dossiers.

This is *not* a generic delete/cascade API.  It removes an entire test dossier
only when every relationship is understood and no official, signed, paid,
exported, or otherwise protected record is present. Unknown relations fail
closed. Real employment records must use rectification or archiving.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import LargeBinary, Text, delete, func, or_, select

from .config import settings
from .database import Base
from .employee_deletion import LABELS, PROFILE_TABLES, employee_references

MAX_ROWS = 150
MAX_BACKUP_BYTES = 2_000_000
ALLOWED = {
    "calculation_records", "generated_certificates", "compliance_events",
    "employee_exits", "final_settlements", "ai_interactions",
    "aguinaldos", "aguinaldo_receipt_details", "labor_deadlines",
    "labor_operations", "vacations",
}
ALWAYS_PROTECTED = {
    "payroll_lines", "documents", "official_certificates", "medical_exams",
    "company_requests",
}
SAFE_CALC_STATUS = {"borrador", "revisar", "anulado"}
SAFE_EVENT_STATUS = {"borrador"}
SAFE_BONUS_STATUS = {"borrador", "revisar", "anulado"}
SAFE_SETTLEMENT_STATUS = {"pendiente de calculo", "en revision"}
SAFE_CERT_STATUS = {"borrador", "emitido", "anulado"}
SAFE_DEADLINE_STATUS = {"pendiente", "borrador", "anulado"}
SAFE_VACATION_STATUS = {"pendiente", "borrador", "anulado"}
SAFE_OPERATION_STATUS = {"borrador", "anulado"}

class PurgeConflict(ValueError):
    pass


def _normalize(value: Any) -> str:
    norm = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in norm if not unicodedata.combining(ch)).lower().strip()


def synthetic_identity(employee) -> bool:
    """Require a visibly synthetic *employee* name; a test company is not enough.

    A real worker imported under a test-company name is NEVER automatically
    eligible just because their employer has 'Prueba' in its name.
    """
    name = _normalize(employee.full_name)
    return any(re.search(pattern, name) for pattern in (
        r"\bpersona de ejemplo\b", r"\b(?:empleado|funcionario|trabajador|persona) (?:de )?prueba\b",
        r"\b(?:persona|empleado|funcionario|trabajador) sintetico\b",
        r"\b(?:persona|empleado|funcionario|trabajador) ficticio\b",
        r"\b(?:empleado|funcionario|trabajador|persona) demo\b",
        r"^(?:test|demo)[\s\-_#0-9]",
        r"\b(?:synthetic|syntetico|sintetica) test\b",
    ))


def _state(row) -> str:
    return _normalize(row.get("status"))


def _present(row: dict, *fields) -> bool:
    return any(row.get(field) not in (None, "", 0, False) for field in fields)


def _unprotected(table: str, row: dict) -> str:
    """Empty reason means one row is eligible for test cleanup."""
    state = _state(row)
    if table == "calculation_records":
        return "" if state in SAFE_CALC_STATUS else "El cálculo está aprobado o tiene un estado no depurable."
    if table == "generated_certificates":
        return "" if state in SAFE_CERT_STATUS else "El certificado tiene un estado que requiere conservación."
    if table == "compliance_events":
        if state not in SAFE_EVENT_STATUS or _present(
            row, "batch_id", "approved_by", "submitted_at", "external_reference", "receipt_storage_key"
        ):
            return "La comunicación fue validada, agrupada, enviada o tiene constancia externa."
        return ""
    if table == "employee_exits":
        return "" if state in {"programado", "efectivo", "cancelado"} else "Procedimiento de egreso no reconocido."
    if table == "final_settlements":
        if state not in SAFE_SETTLEMENT_STATUS or _present(
            row, "approved_amount", "approved_by", "approved_at", "payment_date",
            "payment_amount", "payment_reference", "payment_method",
            "receipt_document_id", "paid_by", "paid_at"
        ):
            return "Liquidación final aprobada, pagada o con comprobantes; debe conservarse."
        return ""
    if table == "aguinaldos":
        return "" if state in SAFE_BONUS_STATUS else "Aguinaldo aprobado o pagado; debe conservarse."
    if table == "aguinaldo_receipt_details":
        return "" if not _present(row, "payment_date", "payment_method") else "Hay datos de pago del aguinaldo."
    if table == "vacations":
        if state not in SAFE_VACATION_STATUS or _present(row, "paid_amount", "payment_date"):
            return "Vacaciones pagadas, aprobadas o con estado no depurable."
        return ""
    if table == "labor_operations":
        return "" if state in SAFE_OPERATION_STATUS else "Operación registrada o consolidada; debe conservarse."
    if table == "labor_deadlines":
        return "" if state in SAFE_DEADLINE_STATUS else "Vencimiento atendido; debe conservarse."
    if table == "ai_interactions":
        return ""
    return "Categoría no autorizada para depuración."


def _row_dicts(db, table, columns, employee_id):
    foreign_clause = or_(*(col == employee_id for col in columns))
    # Never load document/file BLOBs, which are protected anyway.
    selected = [column for column in table.columns if not isinstance(column.type, LargeBinary)]
    rows = list(db.execute(select(*selected).where(foreign_clause).limit(MAX_ROWS + 1)).mappings())
    return [dict(row) for row in rows]


def _canonical(value):
    return json.dumps(value, default=str, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def purge_preview(db, employee):
    """Recompute under lock before deletion; generated preview is never authoritative."""
    by_table: dict[str, list[dict]] = {}
    problems = []
    groups = []
    permitted = synthetic_identity(employee)
    if not permitted:
        problems.append("El nombre del funcionario no lo identifica claramente como dato sintético. "
                        "Los legajos de trabajadores reales se conservan y se rectifican; no se depuran.")
    for table, columns in employee_references():
        rows = _row_dicts(db, table, columns, employee.id)
        if not rows:
            continue
        name = table.name
        by_table[name] = rows
        groups.append({"key": name, "label": LABELS.get(name, "Otros registros vinculados"),
                       "count": len(rows), "ids": [row["id"] for row in rows]})
        if len(rows) > MAX_ROWS:
            problems.append(f"{name}: supera el máximo de {MAX_ROWS} registros para revisión individual.")
            continue
        if name in PROFILE_TABLES:
            continue
        if name in ALWAYS_PROTECTED or name not in ALLOWED:
            problems.append(f"{LABELS.get(name, name)}: la categoría exige conservación o revisión independiente.")
            continue
        for row in rows:
            reason = _unprotected(name, row)
            if reason:
                problems.append(f"{LABELS.get(name, name)} #{row['id']}: {reason}")
    if sum(len(rows) for rows in by_table.values()) > MAX_ROWS:
        problems.append("Hay demasiados antecedentes vinculados para una depuración segura de un solo paso.")

    # Do not delete a parent row if an unselected child references it. This
    # catches both known and future FK relationships without relying on CASCADE.
    removed = {"employees": {employee.id}}
    removed.update({name: {row["id"] for row in rows} for name, rows in by_table.items()})
    for child in Base.metadata.sorted_tables:
        if child.name == "audit_logs":
            continue
        pk = list(child.primary_key.columns)
        if len(pk) != 1:
            continue
        for fk in child.foreign_keys:
            parent = fk.column.table.name
            ids = removed.get(parent)
            if not ids:
                continue
            key = fk.parent
            referenced = set(db.scalars(select(pk[0]).where(key.in_(ids)).limit(MAX_ROWS + 1)))
            extra = referenced - removed.get(child.name, set())
            if extra:
                problems.append(f"{child.name}: contiene {len(extra)} relación(es) externas que deben conservarse "
                                f"(dependencia en {parent}).")
    # Digest includes all safe rows and employee fields, not just counts.
    employee_data = {col.name: getattr(employee, col.name) for col in employee.__table__.columns}
    backup = {"format": "digit-laboral-test-dossier-v1",
              "employee": employee_data, "records": by_table}
    data = _canonical(backup)
    if len(data.encode("utf-8")) > MAX_BACKUP_BYTES:
        problems.append("El expediente excede el tamaño seguro del respaldo JSON.")
    fingerprint = hashlib.sha256(data.encode("utf-8")).hexdigest()
    unique_problems = list(dict.fromkeys(problems))
    code = employee.employee_code if employee.employee_code is not None else f"ID-{employee.id}"
    return {
        "groups": groups, "total": sum(len(r) for r in by_table.values()),
        "problems": unique_problems, "can_purge": bool(permitted and not unique_problems),
        "confirmation": f"DEPURAR {code}", "fingerprint": fingerprint,
        "backup": backup, "by_table": by_table,
    }


def signed_preview(user, employee, preview):
    values = {"user_id": user.id, "company_id": employee.company_id,
              "employee_id": employee.id, "fingerprint": preview["fingerprint"]}
    return URLSafeTimedSerializer(settings.secret_key, salt="synthetic-dossier-purge-v1").dumps(values)


def verify_preview(token, user, employee, preview):
    try:
        claim = URLSafeTimedSerializer(settings.secret_key, salt="synthetic-dossier-purge-v1").loads(token, max_age=600)
    except (BadData, ValueError, TypeError):
        return False
    return claim == {"user_id": user.id, "company_id": employee.company_id,
                     "employee_id": employee.id, "fingerprint": preview["fingerprint"]}


def remove_test_dossier(db, employee, preview):
    if not preview["can_purge"]:
        raise PurgeConflict("El expediente contiene antecedentes que no se pueden depurar.")
    # Reverse FK topology, no cascade or implicit orphaning, all in one DB transaction.
    for table in reversed(Base.metadata.sorted_tables):
        if table.name == "employees":
            continue
        rows = preview["by_table"].get(table.name, [])
        if not rows:
            continue
        ids = [row["id"] for row in rows]
        result = db.execute(delete(table).where(table.c.id.in_(ids)))
        if result.rowcount != len(ids):
            raise PurgeConflict(f"La cantidad de registros cambió al depurar {table.name}.")
    from .models import Employee
    result = db.execute(delete(Employee.__table__).where(Employee.id == employee.id))
    if result.rowcount != 1:
        raise PurgeConflict("No se pudo eliminar el legajo de prueba.")
