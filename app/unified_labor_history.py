"""Read-only unified projections for operational and imported labor records.

Historical DOS records remain EmployeeEvent source evidence; displaying them in
the same list as current records does not create operational calculations,
vacation balances, payment receipts, notices or approvals.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from math import ceil
from typing import Any

from sqlalchemy import String, cast, func, literal, or_, select, union_all
from sqlalchemy.orm import Session, selectinload

from .legacy_notice_import import EVENT_TYPE as NOTICE_EVENT_TYPE, legacy_notice_data
from .legacy_vacation_import import EVENT_TYPE as VACATION_EVENT_TYPE, event_legacy_data
from .legacy_salary_mov_import import EVENT_TYPE as MOV_EVENT_TYPE, event_data as mov_event_data
from .legacy_liq_import import EVENT_TYPE as LIQ_EVENT_TYPE, liq_event_data
from .models import CalculationRecord, Employee, EmployeeEvent, Vacation, HistoricalMovReconciliation

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

    mov_reviews = {
        review.event_id: review for review in db.scalars(
            select(HistoricalMovReconciliation).where(
                HistoricalMovReconciliation.event_id.in_(archive_ids)
            )
        )
    } if archive_ids and live_model is CalculationRecord else {}
    rows = []
    for kind, record_id in keys:
        if kind == "current" and record_id in live:
            rows.append(_live_calculation(live[record_id])
                        if live_model is CalculationRecord else _live_vacation(live[record_id]))
        elif kind == archived_kind and record_id in archive:
            record = archive[record_id]
            if archived_kind == "vacation" or record.event_type == VACATION_EVENT_TYPE:
                rows.append(_legacy_vacation(record))
            elif record.event_type == MOV_EVENT_TYPE:
                rows.append(_legacy_salary(record, mov_reviews.get(record.id)))
            elif record.event_type == LIQ_EVENT_TYPE:
                rows.append(_legacy_settlement(record))
            else:
                rows.append(_legacy_notice(record))
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
        url=(f"/app/reports/liquidaciones-salarios/{record.id}"
             if record.calculation_type in {"salary", "suite_salary"}
             else f"/app/calculations/{record.id}/certificate"),
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


def _legacy_salary(event: EmployeeEvent, review: HistoricalMovReconciliation | None = None) -> dict:
    source = mov_event_data(event.detail) or {}
    values = source.get("values") or {}
    amount = values.get("SALARI") or None
    return dict(
        origin="imported", id=event.id, date=event.effective_date,
        employee=event.employee, company=event.employee.company,
        label="Salario", period=source.get("period") or event.effective_date.strftime("%Y-%m"),
        amount=amount, status="Aprobado",
        detail=(
            "Antecedente vinculado a una liquidación aprobada existente; no constituye un pago nuevo."
            if review and review.status == "Conciliado" else
            "Antecedente revisado profesionalmente; sin constancia de pago ni recibo nuevo."
            if review and review.status == "Validado como antecedente" else
            "Remuneración aprobada e incluida en el historial. Exportable cuando contiene los datos requeridos; no constituye constancia de pago."
        ),
        reconciliation_url=f"/app/mov-conciliation/{event.id}",
        source=source, days=values.get("DIATRA"), used_days=None, balance=None,
        url=("/app/reports/liquidaciones-salarios?employee_id=" + str(event.employee_id)
             + "&period=" + (source.get("period") or event.effective_date.strftime("%Y-%m"))
             + "&source=historical"),
        record=event, can_use_document=False,
    )


def _legacy_settlement(event: EmployeeEvent) -> dict:
    source = liq_event_data(event) or {}
    values = source.get("values") or {}
    pieces = []
    for key, label in (("AGUINA", "Aguinaldo"), ("CAUSAD", "Vac. causadas"),
                       ("PROPOR", "Vac. proporcionales"), ("PREAVI", "Preaviso"),
                       ("INDEMN", "Indemnización")):
        value = values.get(key)
        if value not in (None, ""):
            pieces.append(f"{label}: {value} Gs.")
    return dict(
        origin="imported", id=event.id, date=event.effective_date,
        employee=event.employee, company=event.employee.company,
        label="Liquidación final",
        period=source.get("departure") or event.effective_date.isoformat(),
        amount=None, status="Aprobado",
        detail="; ".join(pieces) + ". Motivo de egreso: " +
               str(values.get("MOTSAL") or "no informado") +
               ". Registro disponible para consulta; no constituye constancia de pago ni genera un recibo nuevo.",
        source=source, days=None, used_days=None, balance=None,
        url=f"/app/employees/{event.employee_id}#timeline",
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



def _superseded_salary_record_ids(
    db: Session, company_ids: tuple[int, ...],
    company_id: int | None, employee_id: int | None,
) -> set[int]:
    """Approved salary rectifications hide their source from the active list.

    A cross-period revision is valid only after approval and only when the
    source is marked Rectificado. Drafts never supersede prior approvals.
    Both documents and their linkage stay accessible for audits.
    """
    if not company_ids:
        return set()
    revisions = select(
        CalculationRecord.id, CalculationRecord.company_id,
        CalculationRecord.employee_id, CalculationRecord.reference_period,
        CalculationRecord.input_json,
    ).where(
        CalculationRecord.company_id.in_(company_ids),
        CalculationRecord.calculation_type == "suite_salary",
        CalculationRecord.source == "Centro laboral",
        CalculationRecord.status.in_(("Aprobado", "Validado")),
        CalculationRecord.input_json.contains('"rectifies_record_id"'),
    )
    if company_id is not None:
        revisions = revisions.where(CalculationRecord.company_id == company_id)
    if employee_id is not None:
        revisions = revisions.where(CalculationRecord.employee_id == employee_id)

    lineage: dict[int, list[tuple[int, int, str]]] = {}
    for revision_id, revision_company, revision_employee, period, raw in db.execute(revisions):
        if revision_employee is None:
            continue
        try:
            source_id = int(json.loads(raw or "{}").get("rectifies_record_id") or 0)
        except (ValueError, TypeError, AttributeError):
            continue
        if source_id > 0 and source_id != revision_id:
            lineage.setdefault(source_id, []).append(
                (revision_company, revision_employee, period)
            )
    if not lineage:
        return set()

    originals = db.execute(select(
        CalculationRecord.id, CalculationRecord.company_id,
        CalculationRecord.employee_id, CalculationRecord.reference_period,
        CalculationRecord.status,
    ).where(
        CalculationRecord.id.in_(lineage),
        CalculationRecord.company_id.in_(company_ids),
        CalculationRecord.calculation_type == "suite_salary",
        CalculationRecord.source == "Centro laboral",
    ))
    return {
        source_id
        for source_id, source_company, source_employee, source_period, source_status in originals
        if any(
            source_company == expected_company and source_employee == expected_employee
            and (source_period == expected_period or source_status == "Rectificado")
            for expected_company, expected_employee, expected_period in lineage[source_id]
        )
    }


def calculation_history_page(
    db: Session, company_ids: list[int] | set[int],
    *, tipo: str | None = None, company_id: int | None = None,
    employee_id: int | None = None,
    page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    include_center_calculations: bool = False,
    include_superseded_salary: bool = False,
    include_deleted: bool = False,
    include_mov_salary: bool = False,
    include_liq_settlement: bool = False,
) -> dict[str, Any]:
    ids = tuple(company_ids)
    superseded = (
        _superseded_salary_record_ids(db, ids, company_id, employee_id)
        if include_center_calculations and tipo in (None, "suite_salary") else set()
    )
    live = select(CalculationRecord).where(
        CalculationRecord.company_id.in_(ids),
    ) if ids else select(CalculationRecord).where(False)
    if not include_center_calculations:
        live = live.where(CalculationRecord.source != "Centro laboral")
    if not include_deleted:
        live = live.where(CalculationRecord.status != "Anulado")
    if superseded and not include_superseded_salary:
        live = live.where(CalculationRecord.id.not_in(superseded))
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

    event_types = (
        ([NOTICE_EVENT_TYPE, VACATION_EVENT_TYPE]
         + ([MOV_EVENT_TYPE] if include_mov_salary else [])
         + ([LIQ_EVENT_TYPE] if include_liq_settlement else []))
        if tipo is None else
        [NOTICE_EVENT_TYPE] if tipo == "notice" else
        [VACATION_EVENT_TYPE] if tipo == "vacation" else
        [MOV_EVENT_TYPE] if tipo in {"salary", "suite_salary"} else
        [LIQ_EVENT_TYPE] if tipo in {"settlement", "suite_settlement"} else []
    )
    events = select(EmployeeEvent).join(
        Employee, EmployeeEvent.employee_id == Employee.id
    ).where(
        Employee.company_id.in_(ids),
        EmployeeEvent.event_type.in_(event_types),
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

    result = _unified_page(db, live_ids, archive_ids, CalculationRecord,
                           "archive", page=page, page_size=page_size)
    result["superseded_count"] = len(superseded)
    for row in result["rows"]:
        if row["origin"] == "current" and row["id"] in superseded:
            row["superseded"] = True
            row["display_status"] = "Sustituido"
        else:
            row["superseded"] = False
            row["display_status"] = "Eliminado" if row["status"] == "Anulado" else row["status"]
    return result


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
