"""Migrated MOV salaries behave as already loaded payroll data for REOP/REI.

Source provenance is retained for auditing. No duplicate operational
CalculationRecord, receipt or payment may be created by a read-only export.
"""
from datetime import date
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import CalculationRecord, Company, Employee, EmployeeEvent, Payroll, Studio, HistoricalMovExportDetail
from app.legacy_salary_mov_import import make_mov_event
from app.approved_salary_import import (
    salary_source_summary, choose_salary_source, approved_salary_records,
)
from app.official_salary_import import prepare_import


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


def test_mov_loaded_salary_is_available_in_same_automatic_reop_source():
    db, engine, company, worker, event = setup_mov()
    try:
        original = event.detail
        summary = salary_source_summary(db, company.id, "2026-10")
        assert summary["approved"] == 1
        assert summary["approved_mov"] == 1
        assert summary["pending"] == 0
        assert choose_salary_source(db, company.id, "2026-10", "auto") == "approved"
        selection, warnings, _ = approved_salary_records(
            db, company, "2026-10", authority="REOP", payment_code="1",
        )
        assert len(selection) == 1, warnings
        assert not warnings
        rows, errors = prepare_import(
            db, company, "2026-10", "REOP", source_type="auto", payment_code="1",
        )
        assert not errors, errors
        assert len(rows) == 1 and len(rows[0]) == 32
        assert rows[0][9] == 3_044_000
        assert rows[0][25] == 273_960
        assert rows[0][5] == 30 and rows[0][7] == 222
        assert db.get(EmployeeEvent, event.id).detail == original
        assert not list(db.scalars(select(CalculationRecord)))
        assert not list(db.scalars(select(Payroll)))
    finally:
        db.close()
        engine.dispose()


def test_draft_does_not_hide_imported_approved_salary():
    db, engine, company, worker, event = setup_mov()
    try:
        db.add(CalculationRecord(
            company_id=company.id, employee_id=worker.id,
            calculation_type="suite_salary", reference_period="2026-10",
            status="Revisar", amount=2_770_040, source="Centro laboral",
            input_json="{}", result_json="{}",
        ))
        db.commit()
        summary = salary_source_summary(db, company.id, "2026-10")
        assert summary["approved"] == 1 and summary["pending"] == 0
        rows, errors = prepare_import(
            db, company, "2026-10", "REOP", source_type="approved", payment_code="1",
        )
        assert len(rows) == 1 and not errors, errors
    finally:
        db.close()
        engine.dispose()


def test_unknown_hours_block_export_without_fabricating_attendance():
    db, engine, company, worker, event = setup_mov(hours="")
    try:
        rows, errors = prepare_import(
            db, company, "2026-10", "REOP", source_type="auto", payment_code="1",
        )
        assert not rows
        assert any("horas ordinarias" in error for error in errors)
    finally:
        db.close()
        engine.dispose()


def test_non_ips_mov_is_not_exported():
    db, engine, company, worker, event = setup_mov(ips_yes=False)
    try:
        summary = salary_source_summary(db, company.id, "2026-10")
        assert summary["approved"] == 0
        rows, errors = prepare_import(
            db, company, "2026-10", "REOP", source_type="auto", payment_code="1",
        )
        assert not rows and errors
    finally:
        db.close()
        engine.dispose()


def test_mov_bookmark_uses_same_approved_salary_path():
    db, engine, company, worker, event = setup_mov()
    try:
        assert choose_salary_source(db, company.id, "2026-10", "mov") == "approved"
        rows, errors = prepare_import(
            db, company, "2026-10", "REOP", source_type="mov", payment_code="1",
        )
        assert len(rows) == 1 and not errors
    finally:
        db.close()
        engine.dispose()


def test_salario1_equal_to_gross_is_not_mistaken_for_salary_net():
    db, engine, company, worker, event = setup_mov()
    try:
        from app.legacy_salary_mov_import import event_data, MARKER
        import json
        payload = event_data(event.detail)
        payload["values"]["SALARI1"] = payload["values"]["SALARI"]
        event.detail = MARKER + json.dumps(payload)
        db.commit()
        rows, errors = prepare_import(
            db, company, "2026-10", "REOP", source_type="auto", payment_code="1",
        )
        assert len(rows) == 1 and not errors, errors
        assert rows[0][9] == 3_044_000
        assert rows[0][25] == 273_960
    finally:
        db.close()
        engine.dispose()


def test_horasx_clock_is_not_converted_into_worked_hours():
    db, engine, company, worker, event = setup_mov(hours="11:54:58")
    try:
        rows, errors = prepare_import(
            db, company, "2026-10", "REOP", source_type="auto", payment_code="1",
        )
        assert rows == []
        assert any("hora de reloj" in error for error in errors)
    finally:
        db.close()
        engine.dispose()


def test_seven_migrated_workers_reconcile_to_official_salary_total_even_with_older_annulments():
    from decimal import Decimal
    from app.legacy_salary_mov_import import event_data, MARKER
    from app.approved_salary_import import salary_excluded_records
    from app.historical_mov_salary_export import mov_salary_records
    import json

    db, engine, company, first, first_event = setup_mov(hours="11:54:58")
    try:
        employees = [(first, first_event, 3_044_000)]
        for i in range(2, 8):
            amount = 3_500_000 if i == 7 else 3_044_000
            worker = Employee(
                company_id=company.id, employee_code=11 + i, full_name=f"TRABAJADOR {i} HIJAZI",
                document_number=str(1234567 + i), admission_date=date(2020, 1, 1),
                base_salary=amount, ips_contributor=True, payment_frequency="Mensual",
                status="Activo",
            )
            db.add(worker)
            db.flush()
            source = dict(
                source_row=i + 1, company_code="2121", employee_code=str(11 + i),
                period="2026-10", legacy_key=f"key-mov-{i}", source_hash=f"{i}" * 64,
                warnings=[],
                raw={"SALARI": str(amount), "SALARI1": str(amount), "SALACT": str(amount),
                     "DESIPS": str(amount * 9 // 100), "DESOTR": "0",
                     "DIATRA": "30", "DIATRA1": "30", "HORASX": "11:54:58",
                     "PAGDEL": "1", "PAGALX": "31", "MONEDA": "Gs"},
            )
            event = make_mov_event(source, worker.id, "MOV.xlsx", "migration@example.invalid")
            db.add(event)
            db.flush()
            employees.append((worker, event, amount))
        for idx, (worker, event, amount) in enumerate(employees):
            payload = event_data(event.detail)
            payload["values"]["SALARI1"] = str(amount)
            payload["values"]["DIATRA"] = "30"
            payload["values"]["DIATRA1"] = "30"
            payload["values"]["HORASX"] = "11:54:58"
            event.detail = MARKER + json.dumps(payload)
            db.add(HistoricalMovExportDetail(
                studio_id=company.studio_id, company_id=company.id,
                employee_id=worker.id, event_id=event.id,
                source_hash=payload["source_hash"],
                days_worked=30, days_paid=30, hours_worked=Decimal("222"),
                pay_basis="monthly", ips_base=amount,
                notes="Comprobantes documentales de asistencia del mes.",
            ))
            if idx in (1, 6):
                db.add(CalculationRecord(
                    company_id=company.id, employee_id=worker.id,
                    calculation_type="salary", reference_period="2026-10",
                    status="Anulado", amount=0, source="Calculadora",
                    input_json="{}", result_json="{}",
                ))
        db.commit()
        summary = salary_source_summary(db, company.id, "2026-10")
        assert summary["approved"] == 7
        assert summary["approved_mov"] == 7
        assert summary["pending"] == 0
        assert not salary_excluded_records(db, company.id, "2026-10", authority="REOP")
        rows, errors = prepare_import(
            db, company, "2026-10", "REOP", source_type="auto", payment_code="1",
        )
        assert errors == [], errors
        assert len(rows) == 7
        assert sum(row[9] for row in rows) == 21_764_000
        assert {row[5] for row in rows} == {30}
        assert {row[7] for row in rows} == {222}
        assert len(list(db.scalars(select(CalculationRecord)))) == 2
    finally:
        db.close()
        engine.dispose()
