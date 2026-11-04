"""Read-only unified projections for operational and imported labor records.

Historical DOS records remain EmployeeEvent source evidence; displaying them in
the same list as current records does not create operational calculations,
vacation balances, payment receipts, notices or approvals.
"""
from __future__ import annotations

from datetime import date, datetime
from math import ceil
from typing import Any

from sqlalchemy import String, cast, func, literal, or_, select, union_all
from sqlalchemy.orm import Session, selectinload

from .legacy_notice_import import EVENT_TYPE as NOTICE_EVENT_TYPE, legacy_notice_data
from .legacy_vacation_import import EVENT_TYPE as VACATION_EVENT_TYPE, event_legacy_data
from .models import CalculationRecord, Employee, EmployeeEvent, Vacation

DEFAULT_PAGE_SIZE = 40
MAX_PAGE_SIZE = 100


def _normalized_date(column):
    """Portable YYYY-MM-DD ordering for SQLite and PostgreSQL."""
    return func.substr(cast(column, String), 1, 10)


def _unified_page(
    db: Session, live_query, archived_query, live_model, archived_kind: str,
    *, page: int, page_size: int, sort_order: str = "recent",
) -> dict[str, Any]:
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError("Tamaño de página fuera del rango permitido.")
    # Both branches are independently scoped by the caller. The union only
    # contains IDs, so pagination happens inside PostgreSQL, not in Python.
    union = union_all(live_query, archived_query).subquery()
    total = int(db.scalar(select(func.count()).select_from(union)) or 0)
    pages = max(1, ceil(total / page_size))
    page = max(1, min(int(page), pages))
    order = (
        (union.c.record_date.asc(), union.c.origin.asc(), union.c.record_id.asc())
        if sort_order == "oldest"
        else (union.c.record_date.desc(), union.c.origin, union.c.record_id.desc())
    )
    keys = db.execute(
        select(union.c.origin, union.c.record_id)
        .order_by(*order)
        .offset((page - 1) * page_size).limit(page_size)
    ).all()

    live_ids = [record_id for kind, record_id in keys if kind == "current"]
    archive_ids = [record_id for kind, record_id in keys if kind == archived_kind]
    live = {
        record.id: record for record in db.scalars(
            select(live_model).where(live_model.id.in_(live_ids))
            .options(selectinload(live_model.employee).selectinload(Employee.company))
        )
    } if live_ids else {}
    archive = {
        record.id: record for record in db.scalars(
            select(EmployeeEvent).where(EmployeeEvent.id.in_(archive_ids))
            .options(selectinload(EmployeeEvent.employee).selectinload(Employee.company))
        )
    } if archive_ids else {}

    rows = []
    for kind, record_id in keys:
        if kind == "current" and record_id in live:
            rows.append(_live_calculation(live[record_id])
                        if live_model is CalculationRecord else _live_vacation(live[record_id]))
        elif kind == archived_kind and record_id in archive:
            record = archive[record_id]
            rows.append(_legacy_vacation(record) if archived_kind == "vacation"
                        or record.event_type == VACATION_EVENT_TYPE else _legacy_notice(record))
    return {
        "rows": rows, "total": total, "page": page, "pages": pages,
        "first": (page - 1) * page_size + 1 if total else 0,
        "last": min(page * page_size, total), "page_size": page_size,
    }


def _live_calculation(record: CalculationRecord) -> dict:
    return dict(
        origin="current", id=record.id, date=record.created_at,
        employee=record.employee, company=record.company,
        label={"notice": "Preaviso", "vacation": "Vacaciones"}.get(
            record.calculation_type, record.calculation_type),
        period=record.reference_period or "—",
        amount=record.amount, status=record.status,
        detail="", source=None, days=None, used_days=None, balance=None,
        url=f"/app/calculations/{record.id}/certificate",
        record=record, can_use_document=True,
    )


def _legacy_notice(event: EmployeeEvent) -> dict:
    info = legacy_notice_data(event) or {}
    days = info.get("days")
    return dict(
        origin="imported", id=event.id, date=event.effective_date,
        employee=event.employee, company=event.employee.company,
        label="Preaviso",
        period=info.get("notice_date_source") or "—",
        amount=None,
        status="Borrado en origen" if info.get("deleted_source") else "Sin conciliar",
        detail=f"Plazo registrado: {days if days is not None else 'sin dato'} días. "
               f"FECSAL: {info.get('departure_date_source') or '—'}",
        source=info, days=days, used_days=None, balance=None,
        url=f"/app/legacy-notices/{event.id}",
        record=event, can_use_document=False,
    )


def _live_vacation(record: Vacation) -> dict:
    return dict(
        origin="current", id=record.id,
        date=record.start_date or record.created_at,
        employee=record.employee, company=record.employee.company,
        label="Vacaciones", period=str(record.period_year),
        amount=None, status=record.status,
        detail="", source=None, days=record.entitled_days,
        used_days=record.used_days,
        balance=record.entitled_days - record.used_days,
        start_date=record.start_date, end_date=record.end_date,
        url=f"/app/vacations/{record.id}", record=record, can_use_document=False,
    )


def _legacy_vacation(event: EmployeeEvent) -> dict:
    info = event_legacy_data(event) or {}
    value = info.get("vacation_amount")
    period = f"{info.get('period_from') or '—'} – {info.get('period_to') or '—'}"
    return dict(
        origin="imported", id=event.id, date=event.effective_date,
        employee=event.employee, company=event.employee.company,
        label="Vacaciones", period=period, amount=value,
        status="Sin conciliar", detail="Importe registrado en origen, no validado como pago.",
        source=info, days=info.get("days"), used_days=None, balance=None,
        start_date=info.get("vacation_start"), end_date=info.get("vacation_end"),
        url=f"/app/vacations/history/{event.id}",
        record=event, can_use_document=False,
    )


def calculation_history_page(
    db: Session, company_ids: list[int] | set[int],
    *, tipo: str | None = None, company_id: int | None = None,
    employee_id: int | None = None,
    page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    include_center_calculations: bool = False,
) -> dict[str, Any]:
    ids = tuple(company_ids)
    live = select(CalculationRecord).where(
        CalculationRecord.company_id.in_(ids),
    ) if ids else select(CalculationRecord).where(False)
    if not include_center_calculations:
        live = live.where(CalculationRecord.source != "Centro laboral")
    if tipo:
        live = live.where(CalculationRecord.calculation_type == tipo)
    if company_id is not None:
        live = live.where(CalculationRecord.company_id == company_id)
    if employee_id is not None:
        live = live.where(CalculationRecord.employee_id == employee_id)

    live_ids = live.with_only_columns(
        literal("current").label("origin"),
        CalculationRecord.id.label("record_id"),
        _normalized_date(CalculationRecord.created_at).label("record_date"),
    ).order_by(None)

    events = select(EmployeeEvent).join(
        Employee, EmployeeEvent.employee_id == Employee.id
    ).where(
        Employee.company_id.in_(ids),
        EmployeeEvent.event_type.in_(
            [NOTICE_EVENT_TYPE, VACATION_EVENT_TYPE]
            if tipo is None else
            [NOTICE_EVENT_TYPE] if tipo == "notice" else
            [VACATION_EVENT_TYPE] if tipo == "vacation" else []
        ),
    ) if ids else select(EmployeeEvent).where(False)
    if company_id is not None:
        events = events.where(Employee.company_id == company_id)
    if employee_id is not None:
        events = events.where(EmployeeEvent.employee_id == employee_id)
    archive_ids = events.with_only_columns(
        literal("archive").label("origin"),
        EmployeeEvent.id.label("record_id"),
        _normalized_date(EmployeeEvent.effective_date).label("record_date"),
    ).order_by(None)

    return _unified_page(db, live_ids, archive_ids, CalculationRecord,
                         "archive", page=page, page_size=page_size)


def vacation_history_page(
    db: Session, company_ids: list[int] | set[int],
    *, company_id: int | None = None, employee_id: int | None = None,
    page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    q: str = "", source: str = "all", status: str = "all",
    sort_order: str = "recent",
) -> dict[str, Any]:
    """Filtros sobre TODOS los movimientos antes de paginar, sin traer miles de filas al navegador.

    Importados siguen siendo evidencia histórica: no se les inventan estados,
    días utilizados ni saldos operativos.
    """
    if source not in {"all", "current", "imported"}:
        raise ValueError("Origen de vacaciones no válido.")
    if status not in {
        "all", "Pendiente", "Aprobada", "Completada", "Anulada",
        "Rechazada", "Cancelada", "Sin conciliar",
    }:
        raise ValueError("Estado de vacaciones no válido.")
    if sort_order not in {"recent", "oldest"}:
        raise ValueError("Orden de vacaciones no válido.")
    ids = tuple(company_ids)
    live = select(Vacation).join(Employee).where(Employee.company_id.in_(ids)) \
        if ids else select(Vacation).where(False)
    archive = select(EmployeeEvent).join(Employee).where(
        Employee.company_id.in_(ids), EmployeeEvent.event_type == VACATION_EVENT_TYPE
    ) if ids else select(EmployeeEvent).where(False)

    if company_id is not None:
        live = live.where(Employee.company_id == company_id)
        archive = archive.where(Employee.company_id == company_id)
    if employee_id is not None:
        live = live.where(Vacation.employee_id == employee_id)
        archive = archive.where(EmployeeEvent.employee_id == employee_id)

    term = q.strip().lower()
    if term:
        # Buscar por nombre, CI, legajo y año/período histórico en toda la base,
        # no únicamente entre los 25 movimientos cargados en pantalla.
        person = or_(
            func.lower(Employee.full_name).contains(term, autoescape=True),
            func.lower(Employee.document_number).contains(term, autoescape=True),
            cast(Employee.employee_code, String).contains(term, autoescape=True),
        )
        live = live.where(or_(
            person, cast(Vacation.period_year, String).contains(term, autoescape=True)
        ))
        archive = archive.where(or_(
            person, func.lower(EmployeeEvent.detail).contains(term, autoescape=True)
        ))

    if source == "current":
        archive = archive.where(False)
    elif source == "imported":
        live = live.where(False)
    if status == "Sin conciliar":
        live = live.where(False)
    elif status != "all":
        live = live.where(Vacation.status == status)
        archive = archive.where(False)

    live_ids = live.with_only_columns(
        literal("current").label("origin"),
        Vacation.id.label("record_id"),
        _normalized_date(func.coalesce(Vacation.start_date, Vacation.created_at)).label("record_date"),
    ).order_by(None)
    archive_ids = archive.with_only_columns(
        literal("vacation").label("origin"),
        EmployeeEvent.id.label("record_id"),
        _normalized_date(EmployeeEvent.effective_date).label("record_date"),
    ).order_by(None)
    return _unified_page(
        db, live_ids, archive_ids, Vacation, "vacation",
        page=page, page_size=page_size, sort_order=sort_order,
    )
