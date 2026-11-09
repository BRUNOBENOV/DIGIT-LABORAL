"""One salary report stream for current liquidations and imported MOV antecedents.

The display union is intentionally read-only: historical MOV rows are not
CalculationRecord, Payroll, SalaryHistory, receipt, approval or payment evidence.
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import String, cast, func, literal, or_, select, union_all
from sqlalchemy.orm import Session, selectinload

from .legacy_salary_mov_import import EVENT_TYPE as MOV_TYPE, event_data
from .models import CalculationRecord, Company, Employee, EmployeeEvent, HistoricalMovReconciliation


def salary_report_unified(
    db: Session,
    allowed_ids: list[int] | set[int],
    calculation_types: set[str] | tuple[str, ...],
    *,
    company_id: int | None = None,
    employee_id: int | None = None,
    period: str = "",
    status: str = "",
    q: str = "",
    source: str = "all",
    superseded_ids: set[int] | None = None,
    sort: str = "period",
    direction: str = "desc",
    page: int = 1,
    page_size: int = 100,
) -> tuple[int, list[SimpleNamespace]]:
    if source not in {"all", "current", "historical"}:
        raise ValueError("Origen salarial inválido.")
    ids = tuple(allowed_ids)
    live_conditions = [
        CalculationRecord.company_id.in_(ids),
        CalculationRecord.calculation_type.in_(tuple(calculation_types)),
        CalculationRecord.employee_id.is_not(None),
    ]
    if superseded_ids:
        live_conditions.append(CalculationRecord.id.not_in(superseded_ids))
    archive_conditions = [
        Employee.company_id.in_(ids),
        EmployeeEvent.event_type == MOV_TYPE,
    ]
    if company_id is not None:
        live_conditions.append(CalculationRecord.company_id == company_id)
        archive_conditions.append(Employee.company_id == company_id)
    if employee_id is not None:
        live_conditions.append(CalculationRecord.employee_id == employee_id)
        archive_conditions.append(EmployeeEvent.employee_id == employee_id)
    if period:
        live_conditions.append(CalculationRecord.reference_period == period)
        archive_conditions.append(
            func.substr(cast(EmployeeEvent.effective_date, String), 1, 7) == period
        )
    if not status:
        live_conditions.append(CalculationRecord.status != "Anulado")
    if status:
        # Aprobado covers live approved salaries and previously imported MOV.
        # Historical approval is a display/integration status only: it does not
        # create a CalculationRecord, receipt, payroll or evidence of payment.
        if status == "Aprobado":
            live_conditions.append(CalculationRecord.status == "Aprobado")
        elif status in {"Incorporado", "Sin conciliar", "Conciliado", "Validado como antecedente"}:
            live_conditions.append(literal(False))
            if status in {"Incorporado", "Sin conciliar"}:
                archive_conditions.append(or_(
                    HistoricalMovReconciliation.id.is_(None),
                    HistoricalMovReconciliation.status.in_(("Incorporado", "Sin conciliar")),
                ))
            else:
                archive_conditions.append(HistoricalMovReconciliation.status == status)
        else:
            live_conditions.append(CalculationRecord.status == status)
            archive_conditions.append(literal(False))
    if q:
        like = f"%{q}%"
        live_conditions.append(or_(
            Company.legal_name.ilike(like),
            Company.ruc.ilike(like),
            Employee.full_name.ilike(like),
            Employee.document_number.ilike(like),
            CalculationRecord.notes.ilike(like),
            CalculationRecord.reference_period.ilike(like),
        ))
        archive_conditions.append(or_(
            Company.legal_name.ilike(like),
            Company.ruc.ilike(like),
            Employee.full_name.ilike(like),
            Employee.document_number.ilike(like),
            func.substr(cast(EmployeeEvent.effective_date, String), 1, 7).ilike(like),
        ))

    common = (
        "origin", "record_id", "period", "date", "company_name", "employee_name",
        "amount", "status",
    )
    current = select(
        literal("current").label(common[0]),
        CalculationRecord.id.label(common[1]),
        CalculationRecord.reference_period.label(common[2]),
        func.substr(cast(CalculationRecord.created_at, String), 1, 10).label(common[3]),
        func.lower(Company.legal_name).label(common[4]),
        func.lower(Employee.full_name).label(common[5]),
        CalculationRecord.amount.label(common[6]),
        CalculationRecord.status.label(common[7]),
    ).join(Company, Company.id == CalculationRecord.company_id).join(
        Employee, Employee.id == CalculationRecord.employee_id
    ).where(*live_conditions)

    historic = select(
        literal("historical").label(common[0]),
        EmployeeEvent.id.label(common[1]),
        func.substr(cast(EmployeeEvent.effective_date, String), 1, 7).label(common[2]),
        func.substr(cast(EmployeeEvent.effective_date, String), 1, 10).label(common[3]),
        func.lower(Company.legal_name).label(common[4]),
        func.lower(Employee.full_name).label(common[5]),
        EmployeeEvent.amount.label(common[6]),
        literal("Aprobado").label(common[7]),
    ).join(Employee, Employee.id == EmployeeEvent.employee_id).join(
        Company, Company.id == Employee.company_id
    ).outerjoin(
        HistoricalMovReconciliation, HistoricalMovReconciliation.event_id == EmployeeEvent.id
    ).where(*archive_conditions)

    if source == "current":
        historic = historic.where(literal(False))
    elif source == "historical":
        current = current.where(literal(False))

    merged = union_all(current, historic).subquery("salary_records_unified")
    total = int(db.scalar(select(func.count()).select_from(merged)) or 0)
    size = page_size if page_size in (25, 50, 100, 200) else 100
    pages = max(1, (total + size - 1) // size)
    page = max(1, min(int(page), pages))
    cols = {
        "period": merged.c.period, "date": merged.c.date,
        "company": merged.c.company_name, "employee": merged.c.employee_name,
        "amount": merged.c.amount, "status": merged.c.status,
    }
    key = cols.get(sort, merged.c.period)
    ordered = key.asc() if direction == "asc" else key.desc()
    selections = db.execute(
        select(merged.c.origin, merged.c.record_id)
        .order_by(ordered.nulls_last(), merged.c.record_id.asc())
        .limit(size).offset((page - 1) * size)
    ).all()
    current_ids = [rid for origin, rid in selections if origin == "current"]
    archive_ids = [rid for origin, rid in selections if origin == "historical"]
    existing = {
        row.id: row for row in db.scalars(
            select(CalculationRecord).where(CalculationRecord.id.in_(current_ids))
            .options(selectinload(CalculationRecord.company), selectinload(CalculationRecord.employee))
        )
    } if current_ids else {}
    previous = {
        row.id: row for row in db.scalars(
            select(EmployeeEvent).where(EmployeeEvent.id.in_(archive_ids))
            .options(selectinload(EmployeeEvent.employee).selectinload(Employee.company))
        )
    } if archive_ids else {}
    review_map = {
        review.event_id: review for review in db.scalars(
            select(HistoricalMovReconciliation).where(
                HistoricalMovReconciliation.event_id.in_(archive_ids)
            )
        )
    } if archive_ids else {}
    items = []
    for origin, rid in selections:
        if origin == "current" and rid in existing:
            record = existing[rid]
            items.append(SimpleNamespace(
                origin="current", id=record.id, record=record, company=record.company,
                employee=record.employee, reference_period=record.reference_period,
                created_at=record.created_at, amount=record.amount,
                status=record.status, raw_values=None, source_row=None, source_filename=None,
            ))
        elif origin == "historical" and rid in previous:
            record = previous[rid]
            source_data = event_data(record.detail) or {}
            review = review_map.get(record.id)
            items.append(SimpleNamespace(
                origin="historical", id=record.id, record=record,
                company=record.employee.company, employee=record.employee,
                reference_period=source_data.get("period") or record.effective_date.strftime("%Y-%m"),
                created_at=record.effective_date, amount=record.amount,
                status="Aprobado",
                reconciliation=review, raw_values=source_data.get("values") or {},
                source_row=source_data.get("source_row"),
                source_filename=source_data.get("filename"), warnings=source_data.get("warnings") or [],
            ))
    return total, items
