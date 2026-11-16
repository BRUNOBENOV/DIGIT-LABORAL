"""Period-aware salary suggestions derived from each employee's dated salary history.

A payroll line stores a single monthly base amount. When a salary change falls
inside that month, this module deliberately flags the line for human review
instead of silently prorating a legally sensitive amount.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import func, select
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
    if not history:
        return max(0, int(employee.base_salary or 0))
    latest = _effective_change(history, effective_on)
    if latest is not None:
        return max(0, int(latest.new_salary or 0))
    # A first adjustment may start the dated ledger of an existing employee.
    # Its previous amount keeps the imported base available for manual review.
    return max(0, int(min(history, key=_salary_order).previous_salary or 0))


def _salary_order(item: SalaryHistory) -> tuple[date, str, int]:
    return item.effective_from, item.created_at.isoformat() if item.created_at else "", item.id or 0


def _effective_change(history: list[SalaryHistory], effective_on: date) -> SalaryHistory | None:
    return max(
        (item for item in history if item.effective_from <= effective_on),
        key=_salary_order, default=None,
    )


def salary_at(db: Session, employee: Employee, effective_on: date) -> int:
    """Resolve a legajo's dated salary using its salary-history ledger."""
    return salary_from_history(
        employee, employee_salary_history(db, employee.id), effective_on
    )


def salary_amount_on(effective_on: date):
    """SQL projection of the dated salary for employee directories and reports."""
    history = SalaryHistory.employee_id == Employee.id
    applicable = select(SalaryHistory.new_salary).where(
        history, SalaryHistory.effective_from <= effective_on,
    ).order_by(SalaryHistory.effective_from.desc(), SalaryHistory.created_at.desc(), SalaryHistory.id.desc())
    prior = select(SalaryHistory.previous_salary).where(history).order_by(
        SalaryHistory.effective_from, SalaryHistory.created_at, SalaryHistory.id,
    )
    return func.coalesce(
        applicable.limit(1).correlate(Employee).scalar_subquery(),
        prior.limit(1).correlate(Employee).scalar_subquery(),
        Employee.base_salary,
    )


def record_salary_change(
    db: Session, employee: Employee, *, amount: int, effective_from: date,
    today: date, reason: str, user_email: str,
) -> SalaryHistory | None:
    """Append a dated change while the caller holds the employee's row lock."""
    history = employee_salary_history(db, employee.id)
    existing = _effective_change(history, effective_from)
    if existing and existing.effective_from == effective_from and existing.new_salary == amount:
        return None
    now = datetime.now(UTC)
    change = SalaryHistory(
        employee_id=employee.id,
        previous_salary=salary_from_history(employee, history, effective_from),
        new_salary=amount,
        effective_from=effective_from,
        reason=reason,
        created_by=user_email,
        created_at=now,
    )
    db.add(change)
    db.flush()
    employee.base_salary = salary_from_history(employee, [*history, change], today)
    employee.updated_by = user_email
    employee.updated_at = now
    return change


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
        detail = (
            "se sugirió el importe previo del legajo y debe verificarse"
            if salary else "la base sugerida quedó en cero y debe verificarse"
        )
        warnings.append(
            f"{employee.full_name}: no hay un salario registrado con vigencia al "
            f"{reference_date:%d/%m/%Y}; {detail}."
        )

    if period_start < employee.admission_date <= period_end:
        warnings.append(
            f"{employee.full_name}: ingreso el {employee.admission_date:%d/%m/%Y} "
            "dentro del período; revisá el prorrateo antes de cerrar."
        )

    if employee.termination_date and period_start <= employee.termination_date <= period_end:
        warnings.append(
            f"{employee.full_name}: egreso efectivo el {employee.termination_date:%d/%m/%Y} "
            "dentro del período; revisar días devengados, liquidación final y evitar duplicaciones. "
            "No se prorratea automáticamente el salario de la línea mensual."
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
