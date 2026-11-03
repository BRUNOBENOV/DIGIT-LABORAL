"""Unified labor history regression tests: source isolation and no false approvals."""
from __future__ import annotations

import json
from datetime import date, datetime

from bs4 import BeautifulSoup
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.legacy_notice_import import EVENT_TYPE as NOTICE_TYPE, MARKER as NOTICE_MARKER
from app.legacy_vacation_import import EVENT_TYPE as VACATION_TYPE, MARKER as VACATION_MARKER
from app.models import (
    CalculationRecord, Company, Employee, EmployeeEvent, Studio, Vacation,
)
from app.unified_labor_history import (
    calculation_history_page, vacation_history_page,
)


def setup_records():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Studio.__table__, Company.__table__, Employee.__table__,
        EmployeeEvent.__table__, CalculationRecord.__table__, Vacation.__table__,
    ])
    db = Session(engine)
    db.add_all([Studio(id=1, name="Estudio A"), Studio(id=2, name="Estudio B")])
    db.add_all([
        Company(id=11, studio_id=1, legal_name="Empresa A", ruc="111-1", legacy_code="1001"),
        Company(id=12, studio_id=2, legal_name="Empresa B", ruc="222-2", legacy_code="1002"),
    ])
    db.add_all([
        Employee(id=21, company_id=11, employee_code=1, full_name="FUNCIONARIO A",
                 document_number="900001", admission_date=date(2020, 1, 1)),
        Employee(id=22, company_id=12, employee_code=1, full_name="FUNCIONARIO B",
                 document_number="900002", admission_date=date(2020, 1, 1)),
    ])
    db.add_all([
        CalculationRecord(id=101, company_id=11, employee_id=21,
                          calculation_type="notice", reference_period="2026-01",
                          amount=330000, status="Revisar", source="Calculadora",
                          created_at=datetime(2026, 1, 3)),
        CalculationRecord(id=102, company_id=12, employee_id=22,
                          calculation_type="notice", reference_period="2026-01",
                          amount=440000, status="Aprobado", source="Calculadora",
                          created_at=datetime(2026, 1, 4)),
    ])
    notice = {
        "source": "LSPRE", "company_code": "1001", "employee_code": "101",
        "source_row": 20, "legacy_key": "notice-one", "source_hash": "a" * 64,
        "notice_date_source": "2025-03-01", "departure_date_source": "2025-04-15",
        "days": 45, "deleted_source": False,
    }
    vacation = {
        "source": "LSVAC", "company_code": "1001", "employee_code": "101",
        "source_row": 30, "legacy_key": "vacation-one", "source_hash": "b" * 64,
        "period_from": "2023-01-01", "period_to": "2023-12-31",
        "vacation_start": "2024-07-01", "vacation_end": "2024-07-12",
        "days": 12, "vacation_amount": "150000.00",
    }
    db.add_all([
        EmployeeEvent(id=201, employee_id=21, event_type=NOTICE_TYPE,
                      title="Preaviso original", detail=NOTICE_MARKER + json.dumps(notice),
                      effective_date=date(2025, 3, 1), created_by="import"),
        EmployeeEvent(id=202, employee_id=21, event_type=VACATION_TYPE,
                      title="Vacaciones original", detail=VACATION_MARKER + json.dumps(vacation),
                      effective_date=date(2024, 7, 1), created_by="import"),
        EmployeeEvent(id=203, employee_id=22, event_type=NOTICE_TYPE,
                      title="Preaviso de otra empresa", detail=NOTICE_MARKER + json.dumps(
                          {**notice, "company_code": "1002"}),
                      effective_date=date(2025, 9, 1), created_by="import"),
    ])
    db.add_all([
        Vacation(id=301, employee_id=21, period_year=2026,
                 entitled_days=18, used_days=5, status="Aprobada",
                 start_date=date(2026, 8, 1), end_date=date(2026, 8, 18)),
        Vacation(id=302, employee_id=22, period_year=2026,
                 entitled_days=12, used_days=2, status="Aprobada",
                 start_date=date(2026, 8, 3)),
    ])
    db.commit()
    return db, engine


def test_calculations_include_notices_without_creating_calculation_records():
    db, engine = setup_records()
    try:
        notice = calculation_history_page(db, {11}, tipo="notice")
        assert notice["total"] == 2
        assert [row["origin"] for row in notice["rows"]] == ["current", "imported"]
        assert notice["rows"][0]["amount"] == 330000
        legacy = notice["rows"][1]
        assert legacy["label"] == "Preaviso"
        assert legacy["status"] == "Sin conciliar"
        assert legacy["days"] == 45
        assert legacy["amount"] is None
        assert legacy["can_use_document"] is False
        assert legacy["url"] == "/app/legacy-notices/201"
        assert calculation_history_page(db, {11}, tipo="vacation")["total"] == 1
        assert calculation_history_page(db, {11})["total"] == 3
        assert calculation_history_page(db, {12}, tipo="notice")["total"] == 2
        assert calculation_history_page(db, {11}, employee_id=22)["total"] == 0
        assert calculation_history_page(db, [], tipo="notice")["total"] == 0
        assert db.query(CalculationRecord).count() == 2
    finally:
        db.close()
        engine.dispose()


def test_vacations_unify_rows_with_distinct_legal_status_and_no_fake_balances():
    db, engine = setup_records()
    try:
        result = vacation_history_page(db, {11})
        assert result["total"] == 2
        current, legacy = result["rows"]
        assert current["origin"] == "current" and current["balance"] == 13
        assert current["used_days"] == 5
        assert legacy["origin"] == "imported"
        assert legacy["days"] == 12
        assert legacy["used_days"] is None
        assert legacy["balance"] is None
        assert legacy["status"] == "Sin conciliar"
        assert legacy["amount"] == "150000.00"
        assert legacy["url"] == "/app/vacations/history/202"
        assert vacation_history_page(db, {11}, employee_id=22)["total"] == 0
        assert vacation_history_page(db, {12})["total"] == 1
        assert db.query(Vacation).count() == 2
    finally:
        db.close()
        engine.dispose()


def test_unified_pagination_keeps_all_records_and_filters():
    db, engine = setup_records()
    try:
        first = calculation_history_page(db, {11}, page=1, page_size=1)
        second = calculation_history_page(db, {11}, page=2, page_size=1)
        third = calculation_history_page(db, {11}, page=3, page_size=1)
        assert [row["id"] for row in first["rows"] + second["rows"] + third["rows"]] == [101, 201, 202]
        assert first["total"] == 3 and first["pages"] == 3
        assert first["first"] == 1 and third["last"] == 3
        assert calculation_history_page(db, {11}, page=999, page_size=1)["page"] == 3
        assert vacation_history_page(db, {11}, page=2, page_size=1)["rows"][0]["id"] == 202
        assert vacation_history_page(db, {11}, page=1, page_size=1)["pages"] == 2
    finally:
        db.close()
        engine.dispose()


def test_synthetic_route_presents_one_vacation_table_with_imported_records(web_case):
    client, db, _, company, employee, _ = web_case
    source = {
        "source": "LSVAC", "source_row": 30, "company_code": "1001",
        "employee_code": "200", "legacy_key": "abc", "source_hash": "c" * 64,
        "period_from": "2024-01-01", "period_to": "2024-12-31",
        "vacation_start": "2025-02-10", "vacation_end": "2025-02-20",
        "days": 10, "vacation_amount": "500000",
    }
    db.add(EmployeeEvent(
        employee_id=employee.id, event_type=VACATION_TYPE,
        title="Vacaciones importadas", detail=VACATION_MARKER + json.dumps(source),
        effective_date=date(2025, 2, 10), created_by="test",
    ))
    db.add(Vacation(
        employee_id=employee.id, period_year=2026,
        entitled_days=12, used_days=2, status="Aprobada",
        start_date=date(2026, 5, 1),
    ))
    db.commit()
    response = client.get("/app/vacations", params={"company_id": company.id, "employee_id": employee.id})
    assert response.status_code == 200, response.text
    page = BeautifulSoup(response.text, "html.parser")
    section = page.select_one("#vacations-records")
    assert section is not None
    assert len(section.select("tbody tr")) == 2
    assert "Sin conciliar" in section.get_text(" ", strip=True)
    assert "Aprobada" in section.get_text(" ", strip=True)
    assert page.select_one("section[id='noticeLegacyHistory']") is None
    assert "Vacaciones migradas del sistema anterior" not in response.text
    assert "/app/vacations/history/" in response.text

    dossier = client.get("/app/employee-history", params={
        "company_id": company.id, "employee_id": employee.id,
    })
    assert dossier.status_code == 200, dossier.text
    page = BeautifulSoup(dossier.text, "html.parser")
    assert page.get_text(" ", strip=True).count("Sin conciliar") >= 1
    assert "ANTECEDENTES DEL SISTEMA ANTERIOR" not in dossier.text
