"""LSPRE exception registry is always read-only and tenant/role scoped."""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.legacy_notice_exceptions import list_notice_exceptions, parse_exception_log
from app.legacy_notice_import import EVENT_TYPE, MARKER
from app.models import Studio, Company, Employee, EmployeeEvent, AuditLog

SHA = "f" * 64


def setup_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Studio.__table__, Company.__table__, Employee.__table__,
        EmployeeEvent.__table__, AuditLog.__table__,
    ])
    db = Session(engine)
    db.add_all([
        Studio(id=1, name="ESTUDIO A"), Studio(id=2, name="ESTUDIO B"),
        Company(id=11, studio_id=1, legal_name="Empresa A", ruc="111-1", legacy_code="2052"),
        Company(id=12, studio_id=2, legal_name="Empresa B", ruc="222-2", legacy_code="2053"),
        Employee(id=21, company_id=11, full_name="Persona de prueba", employee_code=1,
                 document_number="900001", admission_date=date(2020, 1, 2)),
    ])
    db.commit()
    return db, engine


def exception_payload(row=113, company="2052", source="LSPRE"):
    return {
        "source": source, "source_sha256": SHA, "source_row": row,
        "source_file": "LSPRE.xlsx", "company_code": company,
        "employee_code": "052060",
        "notice_date_source": "2023-02-10",
        "departure_date_source": "2023-03-27",
        "days": 45, "deleted_marker_raw": "S",
        "exception_type": "conflicto_fuente",
        "reason": "Dos versiones contradictorias.",
        "status": "Pendiente de revisión documental",
    }


def add_exception(db, studio_id=1, row=113, company="2052", source="LSPRE"):
    db.add(AuditLog(
        studio_id=studio_id, user_email="auditor@test.local",
        action="pendiente_conciliacion", entity="lspre_excepcion",
        entity_id=f"{SHA}:{row}", detail=json.dumps(exception_payload(row, company, source)),
    ))
    db.commit()


def test_exception_view_is_isolated_by_studio_and_authorized_companies():
    db, engine = setup_db()
    try:
        add_exception(db, studio_id=1, row=113)
        add_exception(db, studio_id=2, row=115, company="2053")
        assert list_notice_exceptions(db, 1, {11})["pending"] == 1
        assert list_notice_exceptions(db, 1, {12})["total"] == 0
        assert list_notice_exceptions(db, 2, {11})["total"] == 0
        assert list_notice_exceptions(db, 2, {12})["total"] == 1
        assert list_notice_exceptions(db, 1, set())["total"] == 0
        assert list_notice_exceptions(db, 0, {11})["total"] == 0
        assert list_notice_exceptions(db, 1, {11})["categories"]["conflicto_fuente"] == 1
    finally:
        db.close()
        engine.dispose()


def test_malformed_audit_records_not_trusted_as_historical_source():
    db, engine = setup_db()
    try:
        add_exception(db, row=113, source="NOT_LSPRE")
        result = list_notice_exceptions(db, 1, {11})
        assert result["total"] == 0
        bad = AuditLog(
            studio_id=1, user_email="auditor@test.local",
            action="pendiente_conciliacion", entity="lspre_excepcion",
            entity_id="forged", detail=json.dumps(exception_payload(row=114)),
        )
        db.add(bad)
        db.commit()
        assert parse_exception_log(bad) is None
        assert list_notice_exceptions(db, 1, {11})["total"] == 0
    finally:
        db.close()
        engine.dispose()


def test_audit_case_automatically_marks_linked_only_when_event_matches():
    db, engine = setup_db()
    try:
        add_exception(db, row=113)
        payload = {
            "source": "LSPRE", "source_row": 113,
            "company_code": "2052", "employee_code": "052060",
            "legacy_key": "key113", "source_hash": "a" * 64,
        }
        db.add(EmployeeEvent(
            employee_id=21, event_type=EVENT_TYPE, title="Preaviso histórico",
            detail=MARKER + json.dumps(payload),
            effective_date=date(2023, 2, 10), created_by="test",
        ))
        db.commit()
        result = list_notice_exceptions(db, 1, {11})
        assert result["pending"] == 0
        assert result["linked"] == 1
        assert result["rows"][0]["event_id"] is not None
        assert len(list(db.scalars(select(Employee)))) == 1
    finally:
        db.close()
        engine.dispose()
