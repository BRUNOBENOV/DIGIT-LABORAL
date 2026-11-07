"""Regression: LSLIQ belongs to the existing final settlement / employee history."""
from __future__ import annotations

import io
from datetime import date, datetime

from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.legacy_liq_import import (
    SOURCE_FIELDS, EVENT_TYPE, historical_liq_detail, liq_event_data,
    make_liq_event, parse_legacy_liq_workbook, preview_liq_import,
)
from app.models import (
    CalculationRecord, Company, Employee, EmployeeEvent,
    EmployeeExit, FinalSettlement, Studio,
)
from app.unified_labor_history import calculation_history_page


def source_bytes(*, duplicate=False, bad_exit=False, negative_notice=False):
    book = Workbook()
    sheet = book.active
    sheet.title = "LSLIQ"
    sheet.append(SOURCE_FIELDS)
    values = {
        "CODEMP": 1323, "CODTRA": 323001,
        "FECENT": datetime(2016, 1, 1),
        "FECSAL": datetime(2020, 5, 10),
        "FECPRE": datetime(2020, 4, 1),
        "RENDES": "D", "CONTES": "N",
        "ANOXXX": 4, "MESXXX": 4, "DIAXXX": 9,
        "SALACT": 3500000, "SALPRO": 3500000,
        "AGUINA": 1458333.33, "DIACAU": 12,
        "CAUSAD": 1400000, "PROPOR": 350000,
        "PREAVI": -300000 if negative_notice else 3500000,
        "INDEMN": 3500000, "MOTSAL": "RENUNCIA",
    }
    if bad_exit:
        values["FECSAL"] = 9999999999
    sheet.append([values.get(k) for k in SOURCE_FIELDS])
    if duplicate:
        copy = dict(values)
        copy["AGUINA"] = 1499999
        sheet.append([copy.get(k) for k in SOURCE_FIELDS])
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def seed(db):
    studio = Studio(name="Estudio LSLIQ")
    db.add(studio)
    db.flush()
    company = Company(
        studio_id=studio.id, company_code=1323, legacy_code="1323",
        legal_name="Empresa histórica LIQ", ruc="1234567-9",
    )
    db.add(company)
    db.flush()
    employee = Employee(
        company_id=company.id, employee_code=1,
        document_number="1111111", full_name="Legajo importado",
        admission_date=date(2016, 1, 1), base_salary=4000000,
        status="Activo", notes="Código(s) histórico(s) CODTRA: 323001",
    )
    db.add(employee)
    db.commit()
    return company, employee


def test_liq_preserves_original_components_without_creating_final_settlement():
    engine = database()
    with Session(engine) as db:
        company, employee = seed(db)
        parsed = parse_legacy_liq_workbook(source_bytes(negative_notice=True), "BASE DE DATOS LIQ.xlsx")
        assert parsed["source_rows"] == 1
        assert parsed["rows"][0]["departure"] == "2020-05-10"
        assert "importe negativo" in " ".join(parsed["rows"][0]["warnings"])
        preview = preview_liq_import(db, parsed, {company.id})
        assert preview["summary"]["ready"] == 1
        row = parsed["rows"][0]
        item = make_liq_event(row, employee.id, parsed["filename"], "contador@example.com")
        db.add(item)
        db.commit()
        loaded = db.scalar(select(EmployeeEvent).where(EmployeeEvent.event_type == EVENT_TYPE))
        assert loaded is not None
        source = liq_event_data(loaded)
        assert source["values"]["PREAVI"] == "-300000"
        assert source["values"]["MOTSAL"] == "RENUNCIA"
        assert "Aguinaldo" in historical_liq_detail(loaded)
        assert loaded.amount is None
        assert db.get(Employee, employee.id).status == "Activo"
        assert db.get(Employee, employee.id).base_salary == 4000000
        assert db.scalar(select(FinalSettlement)) is None
        assert db.scalar(select(EmployeeExit)) is None
        assert db.scalar(select(CalculationRecord)) is None
        repeated = preview_liq_import(db, parsed, {company.id})
        assert repeated["summary"]["already_imported"] == 1
        assert repeated["summary"]["ready"] == 0


def test_liq_conflicts_and_impossible_dates_are_not_imported():
    engine = database()
    with Session(engine) as db:
        company, _ = seed(db)
        duplicates = parse_legacy_liq_workbook(source_bytes(duplicate=True), "LSLIQ.xlsx")
        result = preview_liq_import(db, duplicates, {company.id})
        assert result["summary"]["conflicts"] == 2
        assert result["summary"]["ready"] == 0
        bad_dates = parse_legacy_liq_workbook(source_bytes(bad_exit=True), "LSLIQ.xlsx")
        issue = preview_liq_import(db, bad_dates, {company.id})
        assert issue["summary"]["ready"] == 0
        assert issue["summary"]["rejected"] == 1


def test_liq_only_appears_in_existing_settlement_and_employee_history():
    engine = database()
    with Session(engine) as db:
        company, employee = seed(db)
        row = parse_legacy_liq_workbook(source_bytes(), "LIQ.xlsx")["rows"][0]
        db.add(make_liq_event(row, employee.id, "LIQ.xlsx", "contador@example.com"))
        db.commit()
        filtered = calculation_history_page(
            db, {company.id}, tipo="suite_settlement",
            employee_id=employee.id, include_center_calculations=True,
            include_liq_settlement=True,
        )
        assert filtered["total"] == 1
        historic = filtered["rows"][0]
        assert historic["origin"] == "imported"
        assert historic["label"] == "Liquidación final · LIQ"
        assert historic["status"] == "Sin conciliar"
        assert historic["can_use_document"] is False
        all_history = calculation_history_page(
            db, {company.id}, employee_id=employee.id,
            include_center_calculations=True, include_liq_settlement=True,
        )
        assert all_history["total"] == 1
        salary_only = calculation_history_page(
            db, {company.id}, tipo="salary", employee_id=employee.id,
            include_mov_salary=True,
        )
        assert salary_only["total"] == 0


def test_liq_cross_studio_and_unmatched_legajo_are_rejected():
    engine = database()
    with Session(engine) as db:
        company, _ = seed(db)
        parsed = parse_legacy_liq_workbook(source_bytes(), "LIQ.xlsx")
        assert preview_liq_import(db, parsed, {company.id})["summary"]["ready"] == 1
        try:
            preview_liq_import(db, parsed, set())
        except ValueError:
            pass
        else:
            assert False, "No debe procesarse un estudio sin empresas autorizadas."
        parsed["rows"][0]["employee_code"] = "999999"
        report = preview_liq_import(db, parsed, {company.id})
        assert report["summary"]["ready"] == 0
        assert report["summary"]["rejected"] == 1
