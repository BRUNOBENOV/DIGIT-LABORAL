"""Read-only historical LSPRE context shared by preaviso, settlement and dossier."""
from __future__ import annotations

import csv
import io
from datetime import date
from math import ceil
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .legacy_notice_import import EVENT_TYPE, legacy_notice_data
from .models import Employee, EmployeeEvent

PAGE_SIZE = 50
CSV_MAX_ROWS = 10000


def notice_history_query(allowed_company_ids: set[int] | list[int], *,
                         company_id: int | None = None, employee_id: int | None = None):
    ids = tuple(allowed_company_ids)
    query = (
        select(EmployeeEvent).join(Employee, EmployeeEvent.employee_id == Employee.id)
        .where(Employee.company_id.in_(ids), EmployeeEvent.event_type == EVENT_TYPE)
    ) if ids else select(EmployeeEvent).where(False)
    if company_id is not None:
        query = query.where(Employee.company_id == company_id)
    if employee_id is not None:
        query = query.where(EmployeeEvent.employee_id == employee_id)
    return query


def notice_history_summary(db: Session, employee_id: int) -> dict:
    result = db.execute(select(
        func.count(EmployeeEvent.id), func.min(EmployeeEvent.effective_date),
        func.max(EmployeeEvent.effective_date),
    ).where(EmployeeEvent.employee_id == employee_id, EmployeeEvent.event_type == EVENT_TYPE)).one()
    return {"count": int(result[0] or 0), "first_date": result[1], "last_date": result[2],
            "legal_status": "Sin conciliación documental"}


def notice_history_page(db: Session, allowed_company_ids: set[int] | list[int], *,
                        company_id: int | None = None, employee_id: int | None = None,
                        page: int = 1, page_size: int = PAGE_SIZE) -> dict:
    if not 1 <= page_size <= 200:
        raise ValueError("Tamaño de página no permitido.")
    base = notice_history_query(allowed_company_ids, company_id=company_id, employee_id=employee_id)
    count = int(db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    pages = max(1, ceil(count / page_size))
    page = max(1, min(page, pages))
    events = list(db.scalars(base.options(
        selectinload(EmployeeEvent.employee).selectinload(Employee.company),
    ).order_by(EmployeeEvent.effective_date.desc(), EmployeeEvent.id.desc())
        .offset((page - 1) * page_size).limit(page_size)))
    return {
        "rows": [{"event": event, "source": legacy_notice_data(event)}
                 for event in events if legacy_notice_data(event)],
        "total": count, "page": page, "pages": pages,
        "first": (page - 1) * page_size + 1 if count else 0,
        "last": min(count, page * page_size),
    }


def notice_history_detail(event: EmployeeEvent) -> str | None:
    info = legacy_notice_data(event)
    if info is None:
        return None
    days = info.get("days")
    state = "Marcado BORRAD=S en origen. " if info.get("deleted_source") else ""
    return (
        f"LSPRE: FECPRE={info.get('notice_date_source') or '—'}; "
        f"FECSAL={info.get('departure_date_source') or '—'}; "
        f"FECSA1={info.get('secondary_date_source') or 'sin dato'}; "
        f"DIAPRE={days if days is not None else 'sin dato'}. "
        f"{state}Antecedente sin constancia de notificación, cumplimiento ni pago."
    )


def _csv(value: Any) -> str:
    if value is None:
        return ""
    text = value.isoformat() if isinstance(value, date) else str(value)
    if text and text.lstrip().startswith(("=", "+", "-", "@", "\r", "\t")):
        return "'" + text
    return text


CSV_HEADERS = [
    "Evento", "Empresa", "Funcionario", "Legajo nuevo", "CODEMP", "CODTRA",
    "FECENT", "FECPRE", "FECSAL", "FECSA1", "DIAPRE", "BORRAD",
    "FECHAX", "HORASX", "USECOD", "Archivo original", "Fila de origen",
    "Clave histórica", "Huella SHA-256", "Estado documental",
]


def notice_history_csv(db: Session, allowed_company_ids: set[int] | list[int], *,
                       company_id: int | None = None, employee_id: int | None = None) -> tuple[str, int]:
    query = notice_history_query(allowed_company_ids, company_id=company_id, employee_id=employee_id)
    events = list(db.scalars(
        query.options(selectinload(EmployeeEvent.employee).selectinload(Employee.company))
        .order_by(EmployeeEvent.effective_date.desc(), EmployeeEvent.id.desc())
        .limit(CSV_MAX_ROWS + 1)
    ))
    if len(events) > CSV_MAX_ROWS:
        raise ValueError("Demasiados registros para exportar. Filtrá por empresa o funcionario.")
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(CSV_HEADERS)
    included = 0
    for event in events:
        info = legacy_notice_data(event)
        if not info:
            continue
        worker = event.employee
        row = [event.id, worker.company.legal_name, worker.full_name, worker.employee_code,
               info.get("company_code"), info.get("employee_code"),
               info.get("admission_source"), info.get("notice_date_source"),
               info.get("departure_date_source"), info.get("secondary_date_source"),
               info.get("days"), "S" if info.get("deleted_source") else info.get("deleted_marker_raw"),
               info.get("updated_source"), info.get("updated_time_source"), info.get("operator_source"),
               info.get("source_filename"), info.get("source_row"),
               info.get("legacy_key"), info.get("source_hash"), "Sin conciliación documental"]
        writer.writerow([_csv(value) for value in row])
        included += 1
    return "\ufeff" + output.getvalue(), included
