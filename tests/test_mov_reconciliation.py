"""MOV reconciliation requires exact evidence, tenant scope and immutable source."""
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.legacy_salary_mov_import import make_mov_event
from app.models import (
    CalculationRecord, Company, Employee, EmployeeEvent,
    HistoricalMovReconciliation, Payroll, Studio,
)
from app.mov_reconciliation import (
    MATCHED, VALIDATED, _bulk_candidates, _save_review, source_amount,
)
from app.salary_report_unified import salary_report_unified
from app.unified_labor_history import calculation_history_page


def seed(db, *, amount=3_044_000, warnings=None):
    studio = Studio(name="MOV estudio")
    db.add(studio)
    db.flush()
    company = Company(studio_id=studio.id, company_code=56, legacy_code="56",
                      legal_name="Empresa MOV", ruc="123456-7")
    db.add(company)
    db.flush()
    employee = Employee(
        company_id=company.id, employee_code=8, full_name="Funcionario MOV",
        document_number="12345678", admission_date=date(2020, 1, 1),
        base_salary=3_044_000,
    )
    db.add(employee)
    db.flush()
    data = dict(source_row=7, company_code="56", employee_code="8", period="2026-10",
                legacy_key="key-hist-1", source_hash="a" * 64,
                warnings=warnings or [],
                raw={"SALARI": str(amount), "DIATRA": "30", "DESIPS": "273960"})
    event = make_mov_event(data, employee.id, "MOV.xlsx", "origen@example.com")
    db.add(event)
    calc = CalculationRecord(
        company_id=company.id, employee_id=employee.id,
        calculation_type="suite_salary", reference_period="2026-10",
        amount=amount, status="Aprobado", source="Centro laboral",
    )
    db.add(calc)
    db.flush()
    return studio, company, employee, event, calc


def test_exact_mov_reconciliation_preserves_source_and_operational_data():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        studio, company, employee, event, calc = seed(db)
        original = event.detail
        matches, total = _bulk_candidates(db, {company.id})
        assert total == 1 and len(matches) == 1
        _, data, target = matches[0]
        actor = SimpleNamespace(studio_id=studio.id, email="contador@example.com")
        _save_review(db, actor, event, data, record=target, notes="Comprobación documental interna")
        db.commit()
        assert db.get(EmployeeEvent, event.id).detail == original
        assert db.scalar(select(Payroll)) is None
        assert db.get(CalculationRecord, calc.id).status == "Aprobado"
        assert db.scalar(select(HistoricalMovReconciliation)).status == MATCHED

        total, rows = salary_report_unified(db, [company.id], ("salary", "suite_salary"),
                                           status="Conciliado", page_size=25)
        assert total == 1 and rows[0].status == MATCHED
        total, rows = salary_report_unified(db, [company.id], ("salary", "suite_salary"),
                                           status="Sin conciliar", page_size=25)
        assert total == 0 and rows == []
        history = calculation_history_page(db, {company.id}, tipo="salary",
                                           include_center_calculations=True)
        assert any(row["status"] == MATCHED for row in history["rows"] if row["origin"] == "imported")
        again, _ = _bulk_candidates(db, {company.id})
        assert not again


def test_mov_without_operational_match_can_be_validated_only_as_evidence():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        studio, company, employee, event, calc = seed(db, warnings=["Revisar jornada"])
        calc.amount -= 1
        db.flush()
        matches, _ = _bulk_candidates(db, {company.id})
        assert not matches
        data = __import__("app.legacy_salary_mov_import", fromlist=["event_data"]).event_data(event.detail)
        actor = SimpleNamespace(studio_id=studio.id, email="contador@example.com")
        _save_review(db, actor, event, data, notes="Diferencia verificada con el documento original")
        db.commit()
        assert db.scalar(select(HistoricalMovReconciliation)).status == VALIDATED
        total, rows = salary_report_unified(db, [company.id], ("salary", "suite_salary"),
                                           status=VALIDATED, page_size=25)
        assert total == 1 and rows[0].status == VALIDATED
        assert db.get(CalculationRecord, calc.id).status == "Aprobado"
        with pytest.raises(HTTPException) as exc:
            _save_review(db, actor, event, data, record=calc)
        assert exc.value.status_code == 409


def test_mov_auto_match_blocks_ambiguous_months_and_unauthorized_companies():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        studio, company, employee, event, calc = seed(db)
        row = dict(source_row=9, company_code="56", employee_code="8",
                   period="2026-10", legacy_key="key-hist-2", source_hash="b" * 64,
                   warnings=[], raw={"SALARI": "3044000"})
        db.add(make_mov_event(row, employee.id, "MOV.xlsx", "origen@example.com"))
        db.flush()
        matches, total = _bulk_candidates(db, {company.id})
        assert total == 2 and not matches
        matches, total = _bulk_candidates(db, set())
        assert total == 0 and matches == []
        assert source_amount({"values": {"SALARI": "3044000.75"}}) is None
        assert source_amount({"values": {"SALARI": "-10"}}) is None
