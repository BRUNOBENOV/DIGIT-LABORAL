"""Migration of LSVAC must be non-destructive and idempotent."""
from __future__ import annotations

import io
from datetime import datetime

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.legacy_vacation_import import (
    EVENT_TYPE, MARKER, event_legacy_data, make_historical_vacation_event,
    parse_legacy_vacation_workbook, vacation_import_preview,
)
from app.models import Company, Employee, EmployeeEvent, Studio, Vacation


def source_workbook(*, duplicate: bool = False, invalid: bool = False) -> bytes:
    wb = Workbook()
    sheet = wb.active
    sheet.title = "LSVAC"
    sheet.append([
        "CODTRA", "CODEMP", "TOTDIA", "FECENT", "FECACT", "PERDES",
        "PERHAS", "INIVAC", "FINVAC", "FECREG", "DIACAU", "SALMIN",
        "SALACT", "JORNAL", "VACACI", "DESIPS", "IPSXXX",
    ])
    line = [
        "00042", "1001", 365, datetime(2024, 1, 1), datetime(2025, 12, 31),
        datetime(2025, 1, 1), datetime(2025, 12, 31),
        datetime(2026, 1, 5), datetime(2026, 1, 20), datetime(2026, 1, 21),
        12, 2899000, 3044000, 101466.67, 1217600.04, 109584.01, "S",
    ]
    sheet.append(line)
    if duplicate:
        sheet.append(line)
    if invalid:
        wrong = list(line)
        wrong[0] = "00043"
        wrong[7] = datetime(2026, 3, 20)
        wrong[8] = datetime(2026, 3, 10)
        sheet.append(wrong)
    result = io.BytesIO()
    wb.save(result)
    wb.close()
    return result.getvalue()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Studio.__table__, Company.__table__, Employee.__table__, EmployeeEvent.__table__,
    ])
    with Session(engine) as session:
        session.add(Studio(id=1, name="Prueba histórica"))
        session.add(Company(id=10, studio_id=1, legacy_code="1001", legal_name="Empresa histórica", ruc="1-0"))
        session.add(Employee(
            id=20, company_id=10, employee_code=42, full_name="PERSONA SINTÉTICA",
            document_number="9000000", admission_date=datetime(2024, 1, 1).date(),
            notes="Importación histórica: trabajadores.xlsx. Código(s) histórico(s) CODTRA: 00042, 00145. Filas de origen: 2, 3.",
        ))
        session.commit()
        yield session
    engine.dispose()


def test_parser_preserves_dates_days_and_original_monetary_values():
    parsed = parse_legacy_vacation_workbook(source_workbook(), "LSVAC.xlsx")
    assert parsed["source_rows"] == 1
    row = parsed["rows"][0]
    assert row["company_code"] == "1001" and row["employee_code"] == "00042"
    assert row["period_from"] == "2025-01-01"
    assert row["period_to"] == "2025-12-31"
    assert row["vacation_start"] == "2026-01-05"
    assert row["vacation_end"] == "2026-01-20"
    assert row["days"] == 12
    assert row["vacation_amount"] == "1217600.04"
    assert row["ips_discount"] == "109584.01"
    assert row["errors"] == []


def test_parser_rejects_bad_dates_and_does_not_infer_days_used():
    parsed = parse_legacy_vacation_workbook(source_workbook(invalid=True), "LSVAC.xlsx")
    bad = parsed["rows"][1]
    assert "Fechas de vacaciones invertidas." in bad["errors"]
    assert bad["days"] == 12


def test_company_and_legacy_employee_linking_works_without_creating_employees(db):
    parsed = parse_legacy_vacation_workbook(source_workbook(duplicate=True), "LSVAC.xlsx")
    plan = vacation_import_preview(db, parsed, {10})
    assert plan["summary"]["source_rows"] == 2
    assert plan["summary"]["ready"] == 1
    assert plan["summary"]["file_duplicates"] == 1
    row = next(r for r in plan["rows"] if r["state"] == "listo")
    assert row["employee_id"] == 20
    event = make_historical_vacation_event(row, parsed["filename"], "importador@local")
    db.add(event)
    db.commit()
    assert event.event_type == EVENT_TYPE
    assert event.detail.startswith(MARKER)
    assert event.amount == 1217600
    assert event_legacy_data(event)["source_hash"] == row["source_hash"]
    assert len(list(db.scalars(select(Employee)))) == 1
    # Sólo EmployeeEvent se añade; jamás un registro operativo de Vacation.
    assert not any(isinstance(item, Vacation) for item in db.new)
    repeat = vacation_import_preview(db, parsed, {10})
    assert repeat["summary"]["ready"] == 0
    assert repeat["summary"]["already_imported"] == 1
    assert repeat["summary"]["file_duplicates"] == 1


def test_unmapped_or_ambiguous_legacy_codes_never_import(db):
    parsed = parse_legacy_vacation_workbook(source_workbook(), "LSVAC.xlsx")
    assert vacation_import_preview(db, parsed, set([999]))["summary"]["rejected"] == 1
    db.add(Employee(
        id=21, company_id=10, employee_code=43, full_name="OTRA PERSONA SINTÉTICA",
        document_number="9000001", admission_date=datetime(2023, 1, 1).date(),
        notes="Código(s) histórico(s) CODTRA: 00042.",
    ))
    db.commit()
    plan = vacation_import_preview(db, parsed, {10})
    assert plan["summary"]["ready"] == 0
    assert plan["summary"]["rejected"] == 1
    assert "ambiguo" in plan["rows"][0]["reason"]


def test_unknown_or_malformed_source_never_writes(db):
    with pytest.raises(ValueError, match="xlsx"):
        parse_legacy_vacation_workbook(b"", "LSVAC.csv")
    with pytest.raises(Exception):
        parse_legacy_vacation_workbook(b"invalid zip", "LSVAC.xlsx")
    assert list(db.scalars(select(EmployeeEvent))) == []
