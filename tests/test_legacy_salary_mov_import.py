"""Regression checks for historical salary MOV imports: no payroll mutation."""
from __future__ import annotations

import io
from datetime import date

from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.legacy_salary_mov_import import (
    EVENT_TYPE, event_data, make_mov_event,
    parse_legacy_mov_workbook, preview_mov_import,
)
from app.models import Company, Employee, EmployeeEvent, Payroll, SalaryHistory, Studio

HEADERS = [
    "CODTRA", "CODEMP", "PAGDEL", "PAGALX", "MESDEX", "ANOXXX",
    "DIATRA", "DIATRA1", "JORNAL", "SALACT", "SALMIN", "SALARI",
    "SALARI1", "HOREXT", "HOR030", "HOR050", "HOR080", "HOR100",
    "HOR130", "COMREM", "DESIPS", "PATIPS", "DESOTR", "CANHIJ",
    "BONIFI", "MONEDA", "FECHAX", "HORASX", "USECOD",
]


def workbook_bytes(*, duplicate=False):
    book = Workbook()
    sheet = book.active
    sheet.append(HEADERS)
    source = {
        "CODTRA": "036486", "CODEMP": "2036", "PAGDEL": 1,
        "PAGALX": 30, "MESDEX": "202602", "DIATRA": 30, "DIATRA1": 30,
        "JORNAL": 100000, "SALACT": 3000000, "SALMIN": 3000000,
        "SALARI": 3000000, "SALARI1": 3000000, "DESIPS": 270000,
        "PATIPS": 495000, "MONEDA": "Gs.",
    }
    sheet.append([source.get(k) for k in HEADERS])
    if duplicate:
        changed = dict(source)
        changed["SALARI"] = 2900000
        sheet.append([changed.get(k) for k in HEADERS])
    handle = io.BytesIO()
    book.save(handle)
    return handle.getvalue()


def fixture_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def seed(session):
    study = Studio(name="Estudio MOV")
    session.add(study)
    session.flush()
    company = Company(
        studio_id=study.id, company_code=2036, legacy_code="2036",
        legal_name="Empresa histórica", ruc="123456-7",
    )
    session.add(company)
    session.flush()
    employee = Employee(
        company_id=company.id, employee_code=486, full_name="Funcionario MOV",
        document_number="1234567", admission_date=date(2010, 1, 1),
        base_salary=3044000, notes="Código(s) histórico(s) CODTRA: 036486",
    )
    session.add(employee)
    session.commit()
    return company, employee


def test_mov_import_preserves_source_and_does_not_create_operational_payroll():
    engine = fixture_db()
    with Session(engine) as db:
        company, employee = seed(db)
        parsed = parse_legacy_mov_workbook(workbook_bytes(), "BASE DE DATOS MOV.csv.xlsx")
        preview = preview_mov_import(db, parsed, {company.id})
        assert preview["summary"]["ready"] == 1
        assert preview["summary"]["warnings"] == 1  # Commercial 30-day February.
        row = parsed["rows"][0]
        assert preview["states"][row["legacy_key"]] == "listo"
        event = make_mov_event(row, employee.id, parsed["filename"], "contador@example.com")
        db.add(event)
        db.commit()
        history = db.scalar(select(EmployeeEvent).where(EmployeeEvent.event_type == EVENT_TYPE))
        assert history is not None
        assert history.amount == 3000000
        assert event_data(history.detail)["values"]["PAGALX"] == "30"
        assert db.scalar(select(Payroll)) is None
        assert db.scalar(select(SalaryHistory)) is None
        assert db.get(Employee, employee.id).base_salary == 3044000
        again = preview_mov_import(db, parsed, {company.id})
        assert again["summary"]["already_imported"] == 1
        assert again["summary"]["ready"] == 0


def test_mov_conflicting_rows_neither_imported():
    engine = fixture_db()
    with Session(engine) as db:
        company, _ = seed(db)
        parsed = parse_legacy_mov_workbook(workbook_bytes(duplicate=True), "MOV.xlsx")
        preview = preview_mov_import(db, parsed, {company.id})
        assert preview["summary"]["conflicts"] == 2
        assert preview["summary"]["ready"] == 0
        assert preview["summary"]["source_rows"] == 2


def test_mov_unknown_code_cannot_link_by_employee_name():
    engine = fixture_db()
    with Session(engine) as db:
        company, _ = seed(db)
        parsed = parse_legacy_mov_workbook(workbook_bytes(), "MOV.xlsx")
        parsed["rows"][0]["company_code"] = "9999"
        preview = preview_mov_import(db, parsed, {company.id})
        assert preview["summary"]["rejected"] == 1
        assert preview["summary"]["ready"] == 0
