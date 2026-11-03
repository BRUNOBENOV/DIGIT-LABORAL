"""Repositorio de excepciones LSPRE conciliadas en auditoría.

Las excepciones no son EmployeeEvent: el archivo antiguo no permite atribuirlas
a un legajo sin identificación suficiente. No afectan cálculo, saldo, egreso
ni expediente del trabajador hasta que exista una conciliación documentada.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .legacy_notice_import import EVENT_TYPE, legacy_notice_data
from .models import AuditLog, Company, Employee, EmployeeEvent

ENTITY = "lspre_excepcion"
ACTION = "pendiente_conciliacion"
SOURCE = "LSPRE"
KNOWN_TYPES = {
    "trabajador_no_migrado": "Trabajador en fuente DOS, no migrado",
    "trabajador_no_identificado": "Sin trabajador identificado",
    "conflicto_fuente": "Conflicto entre filas de origen",
}


def parse_exception_log(log: AuditLog) -> dict[str, Any] | None:
    """Read only records with matching marker, immutable source and audit key."""
    if log.entity != ENTITY or log.action != ACTION:
        return None
    try:
        record = json.loads(log.detail or "")
        if not isinstance(record, dict) or record.get("source") != SOURCE:
            return None
        sha = record.get("source_sha256")
        row = int(record.get("source_row"))
        if not isinstance(sha, str) or len(sha) != 64 or row < 2:
            return None
        if log.entity_id != f"{sha}:{row}":
            return None
        if record.get("exception_type") not in KNOWN_TYPES:
            return None
        return record
    except (ValueError, TypeError, OverflowError):
        return None


def list_notice_exceptions(db: Session, studio_id: int, allowed_company_ids: set[int]) -> dict:
    """Authoritative per-studio source quarantine; zero trust for JSON audit data."""
    if not studio_id or not allowed_company_ids:
        return {"rows": [], "total": 0, "pending": 0, "linked": 0, "categories": {}}

    companies = list(db.scalars(select(Company).where(
        Company.id.in_(allowed_company_ids), Company.studio_id == studio_id
    )))
    by_code: dict[str, list[Company]] = {}
    for company in companies:
        code = str(company.legacy_code or "").strip()
        if code:
            by_code.setdefault(code, []).append(company)

    logs = list(db.scalars(select(AuditLog).where(
        AuditLog.studio_id == studio_id,
        AuditLog.entity == ENTITY,
        AuditLog.action == ACTION,
    ).order_by(AuditLog.id)))

    historical_events = list(db.scalars(
        select(EmployeeEvent)
        .join(Employee, EmployeeEvent.employee_id == Employee.id)
        .where(
            Employee.company_id.in_(allowed_company_ids),
            EmployeeEvent.event_type == EVENT_TYPE,
        )
    ))
    by_source_row: dict[tuple[str, str, int], int] = {}
    for event in historical_events:
        payload = legacy_notice_data(event)
        if not payload:
            continue
        try:
            key = (str(payload.get("company_code") or ""),
                   str(payload.get("employee_code") or ""),
                   int(payload.get("source_row")))
            by_source_row[key] = event.id
        except (ValueError, TypeError, OverflowError):
            continue

    records = []
    seen = set()
    for log in logs:
        item = parse_exception_log(log)
        if item is None or log.entity_id in seen:
            continue
        source_company = str(item.get("company_code") or "").strip()
        companies_found = by_code.get(source_company, [])
        if len(companies_found) != 1:
            # Do not leak source data belonging to other companies.
            continue
        seen.add(log.entity_id)
        code = str(item.get("employee_code") or "")
        rownum = int(item["source_row"])
        matching_id = by_source_row.get((source_company, code, rownum))
        records.append({
            "log_id": log.id,
            "source": item,
            "company": companies_found[0],
            "status": "Vinculado" if matching_id is not None else "Pendiente",
            "event_id": matching_id,
            "category_label": KNOWN_TYPES[item["exception_type"]],
        })
    records.sort(key=lambda obj: int(obj["source"]["source_row"]))
    pending = sum(row["status"] == "Pendiente" for row in records)
    categories = {
        key: sum(row["source"].get("exception_type") == key and row["status"] == "Pendiente"
                 for row in records)
        for key in KNOWN_TYPES
    }
    return {"rows": records, "total": len(records), "pending": pending,
            "linked": len(records) - pending, "categories": categories}
