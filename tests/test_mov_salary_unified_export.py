"""Historical MOV salary rows remain auditable, not REOP/REI export sources.

Only approved operational CalculationRecord rows or an explicitly closed payroll
are official export sources. Status "Aprobado" in history is not an export grant.
"""
from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import CalculationRecord, Company, Employee, EmployeeEvent, Payroll, Studio
from app.legacy_salary_mov_import import make_mov_event
from app.approved_salary_import import (
    salary_source_summary, choose_salary_source, approved_salary_records,
    salary_excluded_records,
)
from app.official_salary_import import prepare_import
from app.unified_labor_history import calculation_history_page


def setup_mov(*, hours="222", ips_yes=True, period="2026-10"):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    studio = Studio(name="Estudio test")
    db.add(studio)
    db.flush()
    company = Company(
        studio_id=studio.id, company_code=2121, legacy_code="2121",
        legal_name="Empresa salario importado", ruc="1234567-8",
        mtess_employer_number="123456", ips_employer_number="654321",
    )
    db.add(company)
    db.flush()
    worker = Employee(
        company_id=company.id, employee_code=11,
        full_name="JUAN PEREZ GOMEZ", document_number="1234567",
        admission_date=date(2020, 1, 1), base_salary=3_044_000,
        ips_contributor=ips_yes, payment_frequency="Mensual", status="Activo",
    )
    db.add(worker)
    db.flush()
    source = dict(
        source_row=2, company_code="2121", employee_code="11",
        period=period, legacy_key="unique-mov-1", source_hash="a" * 64,
        warnings=[],
        raw={
            "SALARI": "3044000", "SALARI1": "2770040",
            "SALACT": "3044000", "DESIPS": "273960",
            "DESOTR": "0", "DIATRA": "21", "DIATRA1": "30",
            "HORASX": hours, "PAGDEL": "1", "PAGALX": "31",
            "MONEDA": "Gs", "COMREM": "0", "BONIFI": "0",
        },
    )
    event = make_mov_event(source, worker.id, "MOV.xlsx", "migration@example.invalid")
    db.add(event)
    db.commit()
    return db, engine, company, worker, event



def test_mov_is_visible_in_history_but_is_not_a_reop_export_source():
    db, engine, company, worker, event = setup_mov()
    try:
        source_original = event.detail
        summary = salary_source_summary(db, company.id, "2026-10")
        assert summary["approved"] == 0
        assert summary["total"] == 0
        assert summary["pending"] == 0
        assert choose_salary_source(db, company.id, "2026-10", "auto") == "payroll"
        assert not list(db.scalars(select(CalculationRecord)))
        selection, warnings, details = approved_salary_records(
            db, company, "2026-10", authority="REOP", payment_code="1",
        )
        assert not selection and warnings and not details
        rows, errors = prepare_import(
            db, company, "2026-10", "REOP", source_type="approved", payment_code="1",
        )
        assert not rows and errors
        history = calculation_history_page(
            db, {company.id}, tipo="salary", include_center_calculations=True,
        )
        assert any(row["origin"] == "imported" and row["status"] == "Aprobado"
                   for row in history["rows"])
        assert event.detail == source_original
    finally:
        db.close()
        engine.dispose()


def test_draft_or_anulment_does_not_turn_mov_into_an_exportable_salary():
    for state in ("Borrador", "Revisar", "Anulado"):
        db, engine, company, worker, event = setup_mov()
        try:
            db.add(CalculationRecord(
                company_id=company.id, employee_id=worker.id,
                calculation_type="suite_salary", reference_period="2026-10",
                status=state, amount=2_770_040, source="Centro laboral",
                input_json="{}", result_json="{}",
            ))
            db.commit()
            summary = salary_source_summary(db, company.id, "2026-10")
            assert summary["approved"] == 0
            assert summary["pending"] == 1
            assert len(salary_excluded_records(db, company.id, "2026-10")) == 1
            source, warnings, _ = approved_salary_records(
                db, company, "2026-10", authority="REOP", payment_code="1",
            )
            assert not source
        finally:
            db.close()
            engine.dispose()


def test_an_existing_approved_salary_is_the_only_one_selected_alongside_mov():
    db, engine, company, worker, event = setup_mov()
    try:
        native = CalculationRecord(
            company_id=company.id, employee_id=worker.id,
            calculation_type="salary", reference_period="2026-10",
            status="Aprobado", amount=2_770_040, source="Calculadora",
            input_json="{}", result_json="{}",
        )
        db.add(native)
        db.commit()
        summary = salary_source_summary(db, company.id, "2026-10")
        assert summary["approved"] == 1
        assert summary["approved_native"] == 1
        assert summary["approved_mov"] == 0
        assert choose_salary_source(db, company.id, "2026-10", "auto") == "approved"
        source, warnings, diagnostics = approved_salary_records(
            db, company, "2026-10", authority="REOP", payment_code="1",
        )
        assert len(source) == 1 and len(diagnostics) == 1
        assert diagnostics[0]["id"] == native.id
        # Malformed native test inputs generate validation warnings; they do
        # not trigger fallback to MOV.
        assert warnings
    finally:
        db.close()
        engine.dispose()


def test_old_mov_bookmark_does_not_bypass_the_operational_source_filter():
    db, engine, company, worker, event = setup_mov()
    try:
        assert choose_salary_source(db, company.id, "2026-10", "mov") == "approved"
        rows, errors = prepare_import(
            db, company, "2026-10", "REOP", source_type="mov", payment_code="1",
        )
        assert rows == [] and errors
    finally:
        db.close()
        engine.dispose()


def test_seven_historical_mov_rows_do_not_generate_any_reop_rows():
    db, engine, company, first, first_event = setup_mov(hours="11:54:58")
    try:
        for i in range(2, 8):
            amount = 3_500_000 if i == 7 else 3_044_000
            worker = Employee(
                company_id=company.id, employee_code=11 + i,
                full_name=f"PERSONA HISTÓRICA {i}",
                document_number=str(1234567 + i),
                admission_date=date(2020, 1, 1), base_salary=amount,
                ips_contributor=True, payment_frequency="Mensual", status="Activo",
            )
            db.add(worker)
            db.flush()
            source = dict(
                source_row=i + 1, company_code="2121", employee_code=str(11 + i),
                period="2026-10", legacy_key=f"key-mov-{i}",
                source_hash=f"{i}" * 64, warnings=[],
                raw={"SALARI": str(amount), "SALARI1": str(amount),
                     "SALACT": str(amount), "DESIPS": str(amount * 9 // 100),
                     "DIATRA": "30", "DIATRA1": "30", "HORASX": "11:54:58"},
            )
            db.add(make_mov_event(source, worker.id, "MOV.xlsx", "migration@example.invalid"))
        db.commit()
        summary = salary_source_summary(db, company.id, "2026-10")
        assert summary["approved"] == 0 and summary["total"] == 0
        rows, errors = prepare_import(
            db, company, "2026-10", "REOP", source_type="approved", payment_code="1",
        )
        assert rows == [] and errors
        assert not list(db.scalars(select(CalculationRecord)))
        assert not list(db.scalars(select(Payroll)))
    finally:
        db.close()
        engine.dispose()
