"""Regression tests for LSPRE import; all identities and records are synthetic."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from types import SimpleNamespace

from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.legacy_notice_import import (
    EVENT_TYPE, MARKER, parse_legacy_notice_workbook, legacy_notice_preview,
    make_notice_event, legacy_notice_data,
)
from app.historical_notice_context import (
    notice_history_summary, notice_history_page, notice_history_csv, notice_history_detail,
)
from app.models import Company, Employee, EmployeeEvent, Studio, Vacation, CalculationRecord


def sample_workbook(*, duplicate=False, altered=False, deleted=False, missing_days=False, unusual=False):
    book = Workbook()
    sheet = book.active
    sheet.title = "lspre"
    sheet.append(["CODTRA", "CODEMP", "FECENT", "FECPRE", "FECSAL",
                  "FECSA1", "DIAPRE", "BORRAD", "FECHAX", "HORASX", "USECOD"])
    record = [
        "052058", "2052", datetime(2010, 1, 5), datetime(2023, 2, 10),
        datetime(2023, 3, 27), datetime(2023, 3, 30),
        None if missing_days else (7 if unusual else 45),
        "S" if deleted else None, datetime(2023, 2, 11), "12:30:00", "096",
    ]
    sheet.append(record)
    if duplicate:
        sheet.append(record)
    if altered:
        row = list(record)
        row[-1] = "094"  # same key but conflicting original operator
        sheet.append(row)
    stream = io.BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


def fixture_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Studio.__table__, Company.__table__, Employee.__table__, EmployeeEvent.__table__,
        Vacation.__table__,
    ])
    db = Session(engine)
    db.add_all([Studio(id=1, name="Estudio A"), Studio(id=2, name="Estudio B")])
    db.add_all([
        Company(id=10, studio_id=1, legal_name="EMPRESA A", ruc="1-1", legacy_code="2052"),
        Company(id=11, studio_id=2, legal_name="EMPRESA B", ruc="2-2", legacy_code="2053"),
    ])
    db.add_all([
        Employee(id=20, company_id=10, employee_code=51, full_name="TRABAJADOR SINTÉTICO",
                 document_number="900001", admission_date=date(2010, 1, 5),
                 notes="Código(s) histórico(s) CODTRA: 052058."),
        Employee(id=21, company_id=11, employee_code=52, full_name="OTRA PERSONA",
                 document_number="900002", admission_date=date(2011, 1, 1),
                 notes="Código(s) histórico(s) CODTRA: 052058."),
    ])
    db.commit()
    return db, engine


def test_parser_preserves_all_source_dates_and_deletion_marker():
    parsed = parse_legacy_notice_workbook(sample_workbook(deleted=True), "LSPRE.xlsx")
    assert parsed["source_rows"] == 1
    row = parsed["rows"][0]
    assert row["company_code"] == "2052"
    assert row["employee_code"] == "052058"
    assert row["notice_date_source"] == "2023-02-10"
    assert row["departure_date_source"] == "2023-03-27"
    assert row["secondary_date_source"] == "2023-03-30"
    assert row["days"] == 45
    assert row["deleted_source"] is True
    assert row["errors"] == []
    assert any("FECSA1" in x for x in row["warnings"])
    assert any("BORRAD" in x for x in row["warnings"])


def test_missing_or_atypical_days_remain_historical_not_inferred():
    missing = parse_legacy_notice_workbook(sample_workbook(missing_days=True), "LSPRE.xlsx")
    unusual = parse_legacy_notice_workbook(sample_workbook(unusual=True), "LSPRE.xlsx")
    assert missing["rows"][0]["days"] is None
    assert any("DIAPRE" in x for x in missing["rows"][0]["warnings"])
    assert unusual["rows"][0]["days"] == 7
    assert any("atípico" in x for x in unusual["rows"][0]["warnings"])


def test_reconcile_links_to_correct_company_and_is_idempotent():
    db, engine = fixture_db()
    try:
        parsed = parse_legacy_notice_workbook(sample_workbook(duplicate=True), "LSPRE.xlsx")
        plan = legacy_notice_preview(db, parsed, {10})
        assert plan["summary"]["ready"] == 1
        assert plan["summary"]["file_duplicates"] == 1
        row = next(x for x in plan["rows"] if x["state"] == "listo")
        assert row["employee_id"] == 20
        db.add(make_notice_event(row, parsed["filename"], "test-user"))
        db.commit()
        history = list(db.scalars(select(EmployeeEvent)))
        assert len(history) == 1
        assert history[0].amount is None
        assert history[0].detail.startswith(MARKER)
        assert history[0].effective_date == date(2023, 2, 10)
        assert legacy_notice_data(history[0])["operator_source"] == "096"
        assert legacy_notice_preview(db, parsed, {10})["summary"]["already_imported"] == 1
        assert not list(db.scalars(select(Vacation)))
    finally:
        db.close()
        engine.dispose()


def test_conflicting_and_missing_links_are_not_imported():
    db, engine = fixture_db()
    try:
        plan = legacy_notice_preview(
            db, parse_legacy_notice_workbook(sample_workbook(altered=True), "LSPRE.xlsx"), {10},
        )
        assert plan["summary"]["ready"] == 1
        assert plan["summary"]["conflicts"] == 1
        assert legacy_notice_preview(
            db, parse_legacy_notice_workbook(sample_workbook(), "LSPRE.xlsx"), {11},
        )["summary"]["rejected"] == 1
        assert not list(db.scalars(select(EmployeeEvent)))
    finally:
        db.close()
        engine.dispose()


def test_notice_history_is_tenant_scoped_read_only_and_csv_safe():
    db, engine = fixture_db()
    try:
        parsed = parse_legacy_notice_workbook(sample_workbook(deleted=True), "LSPRE.xlsx")
        plan = legacy_notice_preview(db, parsed, {10})
        db.add(make_notice_event(plan["rows"][0], parsed["filename"], "auditor"))
        db.commit()
        assert notice_history_page(db, {11})["total"] == 0
        result = notice_history_page(db, {10}, employee_id=20)
        assert result["total"] == 1 and result["rows"][0]["source"]["deleted_source"]
        assert notice_history_page(db, {10}, employee_id=21)["total"] == 0
        assert notice_history_summary(db, 20)["count"] == 1
        text = notice_history_detail(result["rows"][0]["event"])
        assert "BORRAD=S" in text and "sin constancia" in text
        csv_data, count = notice_history_csv(db, {10})
        assert count == 1
        lines = list(csv.reader(io.StringIO(csv_data.lstrip("\ufeff")), delimiter=";"))
        assert len(lines) == 2
        assert lines[1][5] == "052058"
        assert lines[1][11] == "S"
        assert not list(db.scalars(select(Vacation)))
    finally:
        db.close()
        engine.dispose()
