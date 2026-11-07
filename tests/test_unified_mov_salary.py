"""Salary MOV must be visible in the EXISTING reports without becoming payroll."""
from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.legacy_salary_mov_import import make_mov_event
from app.models import CalculationRecord, Company, Employee, Payroll, Studio
from app.salary_report_unified import salary_report_unified
from app.unified_labor_history import calculation_history_page


def create_case():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def prepare(db: Session):
    studio = Studio(name="Contabilidad histórica")
    db.add(studio)
    db.flush()
    company = Company(studio_id=studio.id, company_code=70, legacy_code="2070",
                      legal_name="Empresa existente", ruc="321-1")
    db.add(company)
    db.flush()
    employee = Employee(company_id=company.id, employee_code=17,
                        document_number="1234567", full_name="Trabajador existente",
                        admission_date=date(2018, 1, 1), base_salary=3050000)
    db.add(employee)
    db.flush()
    current = CalculationRecord(
        company_id=company.id, employee_id=employee.id, calculation_type="suite_salary",
        reference_period="2026-02", amount=2700000,
        status="Aprobado", source="Centro laboral",
    )
    db.add(current)
    row = {
        "source_row": 31, "company_code": "2070", "employee_code": "17",
        "period": "2026-02", "legacy_key": "abc010", "source_hash": "ccc020",
        "warnings": [], "raw": {"SALARI": "3000000.55", "SALARI1": "2730000",
                                "DIATRA": "30", "DESIPS": "270000"},
    }
    db.add(make_mov_event(row, employee.id, "BASE DE DATOS MOV.csv.xlsx", "contador@test.com"))
    db.commit()
    return company, employee


def test_mov_and_current_appear_together_in_existing_salary_report():
    engine = create_case()
    with Session(engine) as db:
        company, employee = prepare(db)
        total, rows = salary_report_unified(
            db, [company.id], ("salary", "suite_salary"),
            company_id=company.id, employee_id=employee.id,
            period="2026-02", page=1, page_size=25,
        )
        assert total == 2
        assert {row.origin for row in rows} == {"historical", "current"}
        old = next(row for row in rows if row.origin == "historical")
        new = next(row for row in rows if row.origin == "current")
        assert old.status == "Sin conciliar"
        assert old.raw_values["SALARI"] == "3000000.55"
        assert old.reference_period == new.reference_period
        assert new.record.source == "Centro laboral"
        assert db.scalar(select(Payroll)) is None


def test_origin_status_period_and_company_filters():
    engine = create_case()
    with Session(engine) as db:
        company, employee = prepare(db)
        for source, status, total_expected, expected in (
            ("historical", "", 1, "historical"),
            ("current", "", 1, "current"),
            ("all", "Sin conciliar", 1, "historical"),
            ("all", "Aprobado", 1, "current"),
            ("all", "", 2, "both"),
        ):
            total, rows = salary_report_unified(
                db, [company.id], ("salary", "suite_salary"), source=source,
                status=status, page=1, page_size=50,
            )
            assert total == total_expected
            if total_expected == 1:
                assert rows[0].origin == expected
        total, rows = salary_report_unified(
            db, [company.id], ("salary", "suite_salary"), period="2026-03"
        )
        assert total == 0 and rows == []
        total, rows = salary_report_unified(
            db, [], ("salary", "suite_salary")
        )
        assert total == 0 and rows == []


def test_mov_in_existing_employee_salary_history_only_when_requested():
    engine = create_case()
    with Session(engine) as db:
        company, employee = prepare(db)
        merged = calculation_history_page(
            db, {company.id}, employee_id=employee.id, page_size=40,
            include_center_calculations=True, include_mov_salary=True,
        )
        assert merged["total"] == 2
        imported = next(row for row in merged["rows"] if row["origin"] == "imported")
        assert imported["label"] == "Salario · MOV"
        assert imported["status"] == "Sin conciliar"
        assert imported["can_use_document"] is False
        notice_only = calculation_history_page(
            db, {company.id}, tipo="notice", employee_id=employee.id,
            include_center_calculations=True, include_mov_salary=True,
        )
        assert notice_only["total"] == 0
