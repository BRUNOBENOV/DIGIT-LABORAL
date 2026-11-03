"""Historical LSVAC links must remain tenant-scoped and legally non-operative."""
from __future__ import annotations

import csv
import io
import json
from datetime import date
from types import SimpleNamespace

from pypdf import PdfReader
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.historical_labor_context import (
    historical_vacation_count, historical_vacation_csv, historical_vacation_detail,
    historical_vacation_page, historical_vacation_summary,
)
from app.legacy_vacation_import import EVENT_TYPE, MARKER
from app.models import Company, Employee, EmployeeEvent, Studio, Vacation
from app.report_export import build_employee_report_pdf


def setup_history():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Studio.__table__, Company.__table__, Employee.__table__,
        EmployeeEvent.__table__, Vacation.__table__,
    ])
    db = Session(engine)
    db.add_all([Studio(id=1, name="Estudio Uno"), Studio(id=2, name="Estudio Dos")])
    db.add_all([
        Company(id=11, studio_id=1, legal_name="Empresa 1", ruc="111-1", legacy_code="1001"),
        Company(id=12, studio_id=2, legal_name="Empresa 2", ruc="222-2", legacy_code="1002"),
    ])
    db.add_all([
        Employee(id=21, company_id=11, employee_code=1, full_name="FUNCIONARIO UNO",
                 document_number="900001", admission_date=date(2020, 1, 1)),
        Employee(id=22, company_id=12, employee_code=2, full_name="=1+1",
                 document_number="900002", admission_date=date(2021, 1, 1)),
    ])
    for id_, emp_id, day in [(101, 21, 3), (102, 21, 7), (103, 22, 9)]:
        record = {
            "source": "LSVAC", "source_filename": "LSVAC.xlsx", "source_row": id_ - 99,
            "legacy_key": f"key-{id_}", "source_hash": f"sha-{id_}",
            "company_code": "1001" if emp_id == 21 else "1002",
            "employee_code": str(emp_id), "period_from": "2024-01-01", "period_to": "2024-12-31",
            "vacation_start": f"2025-03-{day:02d}", "vacation_end": f"2025-03-{day+2:02d}",
            "days": 3, "vacation_amount": "100050.75", "ips_discount": "9004.57",
            "salary_snapshot": "3044000.00", "daily_wage": "101467.00", "ips_flag": "S",
        }
        db.add(EmployeeEvent(id=id_, employee_id=emp_id, event_type=EVENT_TYPE,
                             title=f"Vacaciones históricas {day}", detail=MARKER + json.dumps(record),
                             effective_date=date(2025, 3, day), created_by="import_test"))
    db.commit()
    return db, engine


def test_historical_page_paginates_without_mixing_tenants_or_running_balances():
    db, engine = setup_history()
    try:
        assert historical_vacation_count(db, {11}) == 2
        assert historical_vacation_count(db, {12}) == 1
        assert historical_vacation_count(db, {11}, employee_id=22) == 0
        assert historical_vacation_count(db, []) == 0
        first = historical_vacation_page(db, {11}, page=1, page_size=1)
        last = historical_vacation_page(db, {11}, page=2, page_size=1)
        assert first["total"] == 2 and first["pages"] == 2 and first["first"] == 1
        assert first["rows"][0]["event"].id == 102
        assert last["rows"][0]["event"].id == 101 and last["last"] == 2
        assert historical_vacation_page(db, {11}, page=999, page_size=1)["page"] == 2
        assert historical_vacation_summary(db, 21) == {
            "count": 2, "first_date": date(2025, 3, 3),
            "last_date": date(2025, 3, 7), "balance_status": "Sin conciliar",
        }
        assert not list(db.scalars(select(Vacation)))
    finally:
        db.close()
        engine.dispose()


def test_source_evidence_is_legible_and_csv_export_is_tenant_safe_and_read_only():
    db, engine = setup_history()
    try:
        report, count = historical_vacation_csv(db, {11}, employee_id=21)
        assert count == 2
        rows = list(csv.reader(io.StringIO(report.lstrip("\ufeff")), delimiter=";"))
        assert len(rows) == 3
        assert "Importe vacaciones original" in rows[0]
        assert "100050.75" in rows[1]
        assert "9004.57" in rows[1]
        assert "No conciliado" in rows[1]
        assert "FUNCIONARIO UNO" in rows[1]
        assert "=1+1" not in report
        other, count_other = historical_vacation_csv(db, {12})
        assert count_other == 1 and "'=1+1" in other
        event = db.get(EmployeeEvent, 101)
        detail = historical_vacation_detail(event)
        assert "Período devengado" in detail and "Antecedente sin conciliación" in detail
        assert not detail.startswith(MARKER) and "{" not in detail
        assert event.detail.startswith(MARKER)
        assert not list(db.scalars(select(Vacation)))
    finally:
        db.close()
        engine.dispose()


def test_integral_pdf_marks_historical_vacations_separately_from_live_balance():
    db, engine = setup_history()
    try:
        employee = db.get(Employee, 21)
        history = historical_vacation_page(db, {11}, employee_id=21)["rows"]
        payload = build_employee_report_pdf(
            company=employee.company, employee=employee,
            calculations=[], certificates=[], vacations=[], aguinaldos=[],
            historical_vacations=history, historical_vacation_count=2,
        )
        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(payload)).pages)
        assert "LSVAC" in text
        assert "No constituyen saldo vigente" in text
        assert "100050.75" in text
        assert "Documentos generados" in text
    finally:
        db.close()
        engine.dispose()
