"""Consulta conjunta y segura de antecedentes laborales importados.

Los eventos LSVAC son *evidencia histórica*, no saldos operativos de vacaciones.
Este módulo es exclusivamente de lectura y se reutiliza en expediente, cálculo,
historial, informes y exportaciones. Las futuras fuentes (p. ej. preaviso)
pueden registrarse por separado sin alterar los cálculos existentes.
"""
from __future__ import annotations

import csv
import io
from datetime import date
from math import ceil
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .legacy_vacation_import import EVENT_TYPE as HISTORICAL_VACATION_TYPE, event_legacy_data
from .models import Employee, EmployeeEvent

PAGE_SIZE = 60
CSV_MAX_ROWS = 25000


def historical_vacation_query(
    allowed_company_ids: set[int] | list[int],
    *,
    company_id: int | None = None,
    employee_id: int | None = None,
):
    """Restrict the source query by the caller's tenant/company authorization."""
    ids = tuple(allowed_company_ids)
    query = (
        select(EmployeeEvent)
        .join(Employee, EmployeeEvent.employee_id == Employee.id)
        .where(
            Employee.company_id.in_(ids),
            EmployeeEvent.event_type == HISTORICAL_VACATION_TYPE,
        )
    ) if ids else select(EmployeeEvent).where(False)
    if company_id is not None:
        query = query.where(Employee.company_id == company_id)
    if employee_id is not None:
        query = query.where(EmployeeEvent.employee_id == employee_id)
    return query


def historical_vacation_count(
    db: Session,
    allowed_company_ids: set[int] | list[int],
    *,
    company_id: int | None = None,
    employee_id: int | None = None,
) -> int:
    query = historical_vacation_query(allowed_company_ids, company_id=company_id, employee_id=employee_id)
    return int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)


def historical_vacation_page(
    db: Session,
    allowed_company_ids: set[int] | list[int],
    *,
    company_id: int | None = None,
    employee_id: int | None = None,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> dict:
    if not 1 <= page_size <= 200:
        raise ValueError("Tamaño de página de historial inválido.")
    total = historical_vacation_count(db, allowed_company_ids, company_id=company_id, employee_id=employee_id)
    pages = max(1, ceil(total / page_size))
    current = max(1, min(int(page), pages))
    query = historical_vacation_query(allowed_company_ids, company_id=company_id, employee_id=employee_id)
    records = list(db.scalars(
        query.options(selectinload(EmployeeEvent.employee).selectinload(Employee.company))
        .order_by(EmployeeEvent.effective_date.desc(), EmployeeEvent.id.desc())
        .offset((current - 1) * page_size)
        .limit(page_size)
    ))
    return {
        "rows": [
            {"event": event, "source": event_legacy_data(event)}
            for event in records if event_legacy_data(event) is not None
        ],
        "total": total,
        "page": current,
        "pages": pages,
        "page_size": page_size,
        "first": (current - 1) * page_size + 1 if total else 0,
        "last": min(total, current * page_size),
    }


def historical_vacation_summary(db: Session, employee_id: int) -> dict:
    """Inventory the source only; never aggregate days as an available balance."""
    row = db.execute(
        select(
            func.count(EmployeeEvent.id),
            func.min(EmployeeEvent.effective_date),
            func.max(EmployeeEvent.effective_date),
        ).where(
            EmployeeEvent.employee_id == employee_id,
            EmployeeEvent.event_type == HISTORICAL_VACATION_TYPE,
        )
    ).one()
    return {"count": int(row[0] or 0), "first_date": row[1], "last_date": row[2],
            "balance_status": "Sin conciliar"}


def historical_vacation_detail(event: EmployeeEvent) -> str | None:
    """Human-readable text; prevent raw JSON from leaking into timelines."""
    source = event_legacy_data(event)
    if source is None:
        return None
    period = f"{source.get('period_from') or '—'} al {source.get('period_to') or '—'}"
    interval = f"{source.get('vacation_start') or '—'} al {source.get('vacation_end') or '—'}"
    days = source.get("days")
    amount = source.get("vacation_amount")
    return (
        f"LSVAC · Período devengado: {period}. Fechas registradas: {interval}. "
        f"Días en origen: {days if days is not None else 'no informados'}. "
        f"Importe en origen: {amount if amount is not None else 'no informado'} Gs. "
        "Antecedente sin conciliación de saldo ni confirmación de pago."
    )


def _csv_cell(value: Any) -> str:
    """Avoid spreadsheet formula injection for strings imported from the DOS source."""
    if value is None:
        return ""
    raw = value.isoformat() if isinstance(value, date) else str(value)
    if raw and raw.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + raw
    return raw


CSV_HEADERS = [
    "ID evento", "Empresa", "Funcionario", "Legajo actual", "CODEMP original", "CODTRA original",
    "Período desde", "Período hasta", "Vacaciones desde", "Vacaciones hasta",
    "Días en origen", "Salario registrado", "Jornal registrado", "Importe vacaciones original",
    "Descuento IPS original", "Bandera IPS original", "Archivo original", "Fila origen",
    "Clave histórica", "Huella de fuente", "Estado conciliación",
]


def historical_vacation_csv(db: Session, allowed_company_ids: set[int] | list[int], *,
                            company_id: int | None = None, employee_id: int | None = None) -> tuple[str, int]:
    """Export original evidence unchanged; no financial rounding/recalculation."""
    query = historical_vacation_query(allowed_company_ids, company_id=company_id, employee_id=employee_id)
    query = query.options(selectinload(EmployeeEvent.employee).selectinload(Employee.company))
    events = list(db.scalars(query.order_by(EmployeeEvent.effective_date.desc(), EmployeeEvent.id.desc()).limit(CSV_MAX_ROWS + 1)))
    if len(events) > CSV_MAX_ROWS:
        raise ValueError("La exportación supera 25.000 movimientos. Seleccioná una empresa o funcionario.")
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=";")
    writer.writerow(CSV_HEADERS)
    count = 0
    for event in events:
        source = event_legacy_data(event)
        if source is None:
            continue
        employee = event.employee
        raw = [
            event.id, employee.company.legal_name, employee.full_name,
            employee.employee_code, source.get("company_code"), source.get("employee_code"),
            source.get("period_from"), source.get("period_to"),
            source.get("vacation_start"), source.get("vacation_end"),
            source.get("days"), source.get("salary_snapshot"), source.get("daily_wage"),
            source.get("vacation_amount"), source.get("ips_discount"), source.get("ips_flag"),
            source.get("source_filename"), source.get("source_row"),
            source.get("legacy_key"), source.get("source_hash"), "No conciliado",
        ]
        writer.writerow([_csv_cell(value) for value in raw])
        count += 1
    return "\ufeff" + out.getvalue(), count
