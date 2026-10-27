"""Period-aware salary suggestions derived from each employee's dated salary history.

A payroll line stores a single monthly base amount. When a salary change falls
inside that month, this module deliberately flags the line for human review
instead of silently prorating a legally sensitive amount.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Employee, SalaryHistory


def employee_salary_history(db: Session, employee_id: int) -> list[SalaryHistory]:
    """Return all salary changes in a deterministic effective-date order."""
    return list(
        db.scalars(
            select(SalaryHistory)
            .where(SalaryHistory.employee_id == employee_id)
            .order_by(
                SalaryHistory.effective_from.asc(),
                SalaryHistory.created_at.asc(),
                SalaryHistory.id.asc(),
            )
        )
    )


def salary_from_history(
    employee: Employee, history: list[SalaryHistory], effective_on: date
) -> int:
    """Resolve the salary in effect on a date, without applying future changes."""
    applicable = [item for item in history if item.effective_from <= effective_on]
    if applicable:
        latest = max(
            applicable,
            key=lambda item: (
                item.effective_from,
                item.created_at.isoformat() if item.created_at else "",
                item.id or 0,
            ),
        )
        return max(0, int(latest.new_salary or 0))

    # Old imported legajos may have no history at all. Preserve their current
    # salary as a compatibility fallback, but never use a known future salary
    # as if it were already effective.
    if not history:
        return max(0, int(employee.base_salary or 0))
    return 0


def salary_at(db: Session, employee: Employee, effective_on: date) -> int:
    """Resolve a legajo's dated salary using its salary-history ledger."""
    return salary_from_history(
        employee, employee_salary_history(db, employee.id), effective_on
    )


def salary_for_period(
    db: Session,
    employee: Employee,
    period_start: date,
    period_end: date,
) -> tuple[int, list[str]]:
    """Suggest a monthly payroll base and return any manual-review warnings.

    Existing employees use the salary effective on the first day of the
    payroll period. New hires use the salary effective on their admission
    date. A mid-period change is surfaced in payroll notes for manual review.
    """
    history = employee_salary_history(db, employee.id)
    reference_date = max(period_start, employee.admission_date)
    salary = salary_from_history(employee, history, reference_date)
    warnings: list[str] = []

    if not history:
        warnings.append(
            f"{employee.full_name}: no hay historial salarial registrado; "
            "verificá manualmente la base precargada."
        )
    elif not any(item.effective_from <= reference_date for item in history):
        warnings.append(
            f"{employee.full_name}: no hay un salario registrado con vigencia al "
            f"{reference_date:%d/%m/%Y}; la base sugerida quedó en cero y debe verificarse."
        )

    if period_start < employee.admission_date <= period_end:
        warnings.append(
            f"{employee.full_name}: ingreso el {employee.admission_date:%d/%m/%Y} "
            "dentro del período; revisá el prorrateo antes de cerrar."
        )

    changes_in_period = [
        item
        for item in history
        if reference_date < item.effective_from <= period_end
        and period_start < item.effective_from
    ]
    for item in changes_in_period:
        warnings.append(
            f"{employee.full_name}: cambio salarial con vigencia "
            f"{item.effective_from:%d/%m/%Y}; revisá el importe del mes "
            "antes de cerrar la nómina."
        )

    return salary, warnings
