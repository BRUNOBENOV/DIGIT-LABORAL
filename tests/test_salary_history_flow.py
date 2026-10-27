from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Branch, Company, Employee, SalaryHistory, Studio
from app.salary_history import salary_at, salary_for_period


def _session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Studio.__table__,
            Company.__table__,
            Branch.__table__,
            Employee.__table__,
            SalaryHistory.__table__,
        ],
    )
    return engine, Session(engine)


def _employee(db: Session, *, salary: int, admission: date = date(2024, 1, 1)) -> Employee:
    studio = Studio(name="Estudio de prueba")
    db.add(studio)
    db.flush()
    company = Company(studio_id=studio.id, legal_name="Empresa de prueba", ruc="80000000-0")
    db.add(company)
    db.flush()
    employee = Employee(
        company_id=company.id,
        full_name="Funcionario de prueba",
        document_number="1234567",
        admission_date=admission,
        base_salary=salary,
    )
    db.add(employee)
    db.flush()
    return employee


def _history(db: Session, employee: Employee, effective: date, salary: int) -> None:
    previous = db.scalar(
        select(SalaryHistory.new_salary)
        .where(
            SalaryHistory.employee_id == employee.id,
            SalaryHistory.effective_from < effective,
        )
        .order_by(SalaryHistory.effective_from.desc(), SalaryHistory.id.desc())
        .limit(1)
    )
    db.add(
        SalaryHistory(
            employee_id=employee.id,
            previous_salary=int(previous or 0),
            new_salary=salary,
            effective_from=effective,
            reason="Prueba",
            created_by="tests",
        )
    )
    db.flush()


def test_salary_at_uses_salary_effective_on_the_requested_date():
    engine, db = _session()
    try:
        employee = _employee(db, salary=3_500_000)
        _history(db, employee, date(2025, 1, 1), 3_000_000)
        _history(db, employee, date(2026, 11, 1), 3_500_000)

        assert salary_at(db, employee, date(2026, 10, 1)) == 3_000_000
        assert salary_at(db, employee, date(2026, 11, 1)) == 3_500_000
    finally:
        db.close()
        engine.dispose()


def test_salary_at_does_not_apply_a_known_future_salary_early():
    engine, db = _session()
    try:
        employee = _employee(db, salary=4_000_000)
        _history(db, employee, date(2030, 1, 1), 4_000_000)

        assert salary_at(db, employee, date(2029, 12, 31)) == 0
    finally:
        db.close()
        engine.dispose()


def test_salary_at_keeps_a_legacy_fallback_when_no_history_exists():
    engine, db = _session()
    try:
        employee = _employee(db, salary=2_750_000)

        assert salary_at(db, employee, date(2026, 10, 1)) == 2_750_000
    finally:
        db.close()
        engine.dispose()


def test_period_salary_warns_when_salary_changes_during_the_month():
    engine, db = _session()
    try:
        employee = _employee(db, salary=3_500_000)
        _history(db, employee, date(2025, 1, 1), 3_000_000)
        _history(db, employee, date(2026, 10, 15), 3_500_000)

        salary, warnings = salary_for_period(
            db, employee, date(2026, 10, 1), date(2026, 10, 31)
        )

        assert salary == 3_000_000
        assert any("15/10/2026" in warning and "revisá" in warning for warning in warnings)
    finally:
        db.close()
        engine.dispose()


def test_period_salary_uses_admission_salary_and_flags_partial_month():
    engine, db = _session()
    try:
        employee = _employee(
            db, salary=2_000_000, admission=date(2026, 10, 15)
        )
        _history(db, employee, date(2026, 10, 15), 2_000_000)

        salary, warnings = salary_for_period(
            db, employee, date(2026, 10, 1), date(2026, 10, 31)
        )

        assert salary == 2_000_000
        assert any("ingreso el 15/10/2026" in warning for warning in warnings)
    finally:
        db.close()
        engine.dispose()


def test_period_salary_flags_when_history_has_only_a_future_salary():
    engine, db = _session()
    try:
        employee = _employee(db, salary=4_000_000)
        _history(db, employee, date(2026, 10, 15), 4_000_000)

        salary, warnings = salary_for_period(
            db, employee, date(2026, 10, 1), date(2026, 10, 31)
        )

        assert salary == 0
        assert any("la base sugerida quedó en cero" in warning for warning in warnings)
    finally:
        db.close()
        engine.dispose()
