"""No-write tests for IPS/REI monthly planilla reconciliation."""
import json
import re
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import CalculationRecord, Company, Employee
from app.portal_reconciliation import SnapshotError, validate_snapshot


def ips_rows(count=7):
    return [
        {
            "document": str(7000000 + index), "name": f"Trabajador de prueba {index + 1}",
            "days_ips": 2 if index == 0 else 30,
            "salary_real_ips": 202933 if index == 0 else 3044000,
            "salary_paid_ips": 202933 if index == 0 else 3044000,
            "movement": "ENTRADA" if index == 0 else "NORMAL",
        }
        for index in range(count)
    ]


def snapshot(rows=None, patronal="0905-61-00498", period="2026-10"):
    return {
        "source": "IPS_REI", "patronal": patronal, "period": period,
        "rows": rows if rows is not None else ips_rows(),
    }


def test_read_only_snapshot_validates_all_seven_workers_and_separates_claims():
    rows = validate_snapshot(snapshot(), "0905-61-00498", "2026-10")
    assert len(rows) == 7
    assert rows[0]["days_ips"] == 2
    assert rows[0]["salary_paid_ips"] == 202933
    assert rows[0]["movement"] == "ENTRADA"
    assert "admission_date" not in rows[0]
    assert "hours_actual" not in rows[0]
    assert "payment_date" not in rows[0]


@pytest.mark.parametrize("bad", [
    snapshot(patronal="0905-61-00001"),
    snapshot(period="2026-11"),
    snapshot(rows=[]),
    snapshot(rows=ips_rows(2)[:1] * 2),
    snapshot(rows=[{**ips_rows(1)[0], "days_ips": 32}]),
    snapshot(rows=[{**ips_rows(1)[0], "salary_paid_ips": -1}]),
    snapshot(rows=[{**ips_rows(1)[0], "salary_paid_ips": True}]),
    {**snapshot(), "source": "REOP"},
])
def test_rejects_wrong_patronal_period_duplicates_or_unreliable_rows(bad):
    with pytest.raises(SnapshotError):
        validate_snapshot(bad, "0905-61-00498", "2026-10")


def login(client):
    response = client.get("/login")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert csrf
    answer = client.post("/login", data={
        "email": "admin@digitlaboral.com.py",
        "password": settings.demo_admin_password,
        "csrf_token": csrf.group(1),
    }, follow_redirects=False)
    assert answer.status_code == 303
    app_page = client.get("/app")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', app_page.text)
    assert csrf
    return csrf.group(1)


def test_reconciliation_api_read_only_matches_prior_employer_and_approved_salary():
    marker = uuid4().hex[:12]
    document_prior = str(8000000 + int(marker[:5], 16))
    document_current = str(9000000 + int(marker[5:10], 16))
    with TestClient(app) as client:
        csrf = login(client)
        with SessionLocal() as db:
            original = db.scalar(select(Company).order_by(Company.id))
            assert original
            prior = Company(studio_id=original.studio_id, legal_name="Previous QA " + marker,
                            ruc="QA-OLD-" + marker, status="Activa")
            current = Company(studio_id=original.studio_id, legal_name="KAJI QA " + marker,
                              ruc="QA-KAJI-" + marker, ips_employer_number="0905-61-00498",
                              status="Activa")
            db.add_all([prior, current])
            db.flush()
            past_worker = Employee(
                company_id=prior.id, employee_code=800111, full_name="Alejandro QA",
                document_number=document_prior, admission_date=date(2022, 1, 1),
                position="Operario", base_salary=3200000, status="Desvinculado",
                termination_date=date(2026, 10, 29),
            )
            existing = Employee(
                company_id=current.id, employee_code=800112, full_name="Otro QA",
                document_number=document_current, admission_date=date(2025, 1, 1),
                position="Operario", base_salary=3044000, status="Activo",
            )
            db.add_all([past_worker, existing])
            db.flush()
            approved = CalculationRecord(
                company_id=current.id, employee_id=existing.id,
                calculation_type="suite_salary", reference_period="2026-10",
                input_json=json.dumps({"days_worked": 30}),
                result_json=json.dumps({"gross": 3044000}),
                amount=2760000, status="Aprobado", source="QA", notes="",
                created_by="qa",
            )
            db.add(approved)
            db.commit()
            ids = prior.id, current.id, past_worker.id, existing.id, approved.id
        try:
            portal = snapshot(rows=[
                {**ips_rows(1)[0], "document": document_prior, "name": "Alejandro QA"},
                {**ips_rows(1)[0], "document": document_current, "name": "Otro QA",
                 "days_ips": 30, "salary_paid_ips": 3044000, "salary_real_ips": 3044000},
            ])
            page = client.get(f"/app/compliance/portal-reconciliation?company_id={ids[1]}&period=2026-10")
            assert page.status_code == 200
            assert "Traer trabajadores de REOP e IPS" in page.text
            response = client.post("/app/compliance/portal-reconciliation/preview", json={
                "company_id": ids[1], "period": "2026-10", "snapshot": portal,
            }, headers={"X-CSRF-Token": csrf})
            assert response.status_code == 200, response.text[:500]
            data = response.json()
            assert data["count"] == 2
            assert data["counts"] == {"same_company":1,"prior_company":1,"not_found":0,"approved":1,"pending":1}
            prior_result, approved_result = data["rows"]
            assert prior_result["employee_id"] is None
            assert f"/app/employees/{ids[2]}/change-company" in prior_result["action"]["url"]
            assert prior_result["days_ips"] == 2
            assert prior_result["salary_paid_ips"] == 202933
            assert prior_result["saved_gross"] is None
            assert approved_result["employee_id"] == ids[3]
            assert approved_result["saved_gross"] == 3044000
            assert approved_result["salary_status"] == "Aprobado"

            bad = client.post("/app/compliance/portal-reconciliation/preview", json={
                "company_id": ids[1], "period": "2026-10",
                "snapshot": snapshot(patronal="9900", rows=portal["rows"]),
            }, headers={"X-CSRF-Token": csrf})
            assert bad.status_code == 422
            with SessionLocal() as db:
                assert db.get(Employee, ids[2]).company_id == ids[0]
                assert db.get(Employee, ids[3]).company_id == ids[1]
                assert db.get(CalculationRecord, ids[4]).amount == 2760000
        finally:
            with SessionLocal() as db:
                db.execute(delete(CalculationRecord).where(CalculationRecord.id == ids[4]))
                db.execute(delete(Employee).where(Employee.id.in_([ids[2], ids[3]])))
                db.execute(delete(Company).where(Company.id.in_([ids[0], ids[1]])))
                db.commit()
