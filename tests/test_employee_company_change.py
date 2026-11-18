"""Safe same-document employer navigation and administrative company correction."""
from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import (
    AuditLog, CalculationRecord, Company, ComplianceEvent, Employee,
    EmployeeComplianceProfile, EmployeeEvent, SalaryHistory,
)


def login(client):
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert page.status_code == 200 and token
    response = client.post("/login", data={
        "email": "admin@digitlaboral.com.py",
        "password": settings.demo_admin_password,
        "csrf_token": token.group(1),
    }, follow_redirects=False)
    assert response.status_code == 303
    dashboard = client.get("/app")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', dashboard.text)
    assert dashboard.status_code == 200 and csrf
    return csrf.group(1)


@contextmanager
def workforce(*, duplicate=False, linked=False):
    marker = uuid4().hex[:15]
    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        source = Company(studio_id=company.studio_id, legal_name="Origen QA " + marker,
                         ruc="QA-" + marker, status="Activa")
        destination = Company(studio_id=company.studio_id, legal_name="Destino QA " + marker,
                              ruc="QB-" + marker, status="Activa")
        db.add_all((source, destination))
        db.flush()
        document = str(9000000000 + int(marker[:8], 16))
        worker = Employee(
            company_id=source.id, employee_code=899000,
            full_name="Funcionario QA " + marker, document_number=document,
            admission_date=date(2024, 4, 1), position="Auxiliar",
            base_salary=3044000, status="Activo",
        )
        db.add(worker)
        db.flush()
        db.add(EmployeeEvent(employee_id=worker.id, event_type="Alta", title="Alta inicial",
                             detail="", effective_date=date(2024, 4, 1)))
        db.add(SalaryHistory(employee_id=worker.id, previous_salary=0, new_salary=3044000,
                             effective_from=date(2024, 4, 1), reason="Salario inicial",
                             created_by="qa"))
        second_id = None
        if duplicate:
            second = Employee(
                company_id=destination.id, employee_code=899001,
                full_name=worker.full_name, document_number=document,
                admission_date=date(2026, 10, 30), position="Auxiliar",
                base_salary=3044000, status="Activo",
            )
            db.add(second)
            db.flush()
            second_id = second.id
        if linked:
            db.add(CalculationRecord(
                company_id=source.id, employee_id=worker.id,
                calculation_type="suite_salary", reference_period="2026-10",
                amount=3044000, status="Aprobado", source="qa",
                notes="Liquidación ficticia, no puede cambiar de patronal",
                created_by="qa",
            ))
        db.commit()
        ids = dict(source=source.id, destination=destination.id, worker=worker.id,
                   second=second_id, document=document)
    try:
        yield ids
    finally:
        with SessionLocal() as db:
            employee_ids = list(db.scalars(
                select(Employee.id).where(
                    Employee.document_number == ids["document"],
                    Employee.company_id.in_([ids["source"], ids["destination"]]),
                )
            ))
            db.execute(delete(ComplianceEvent).where(ComplianceEvent.employee_id.in_(employee_ids)))
            db.execute(delete(CalculationRecord).where(CalculationRecord.employee_id.in_(employee_ids)))
            db.execute(delete(EmployeeEvent).where(EmployeeEvent.employee_id.in_(employee_ids)))
            db.execute(delete(SalaryHistory).where(SalaryHistory.employee_id.in_(employee_ids)))
            db.execute(delete(EmployeeComplianceProfile).where(EmployeeComplianceProfile.employee_id.in_(employee_ids)))
            db.execute(delete(AuditLog).where(
                AuditLog.entity == "funcionario",
                AuditLog.entity_id.in_([str(i) for i in employee_ids]),
                AuditLog.action.in_(["rectificar_empresa", "alta_nuevo_empleador"]),
            ))
            db.execute(delete(Employee).where(Employee.id.in_(employee_ids)))
            db.execute(delete(Company).where(Company.id.in_([ids["source"], ids["destination"]])))
            db.commit()


def correction_token(html):
    found = re.search(r'name="correction_token" value="([^"]+)"', html)
    assert found, "The review token was not shown"
    return found.group(1)


def form_data(csrf, token, ids):
    return dict(
        csrf_token=csrf, correction_token=token,
        destination_company_id=str(ids["destination"]),
        new_employee_code="899002",
        reason="La empresa se seleccionó por error al registrar el legajo.",
        acknowledgment="confirm",
    )


def test_company_correction_moves_only_clean_dossier_and_keeps_salary_initial():
    with TestClient(app) as client, workforce() as ids:
        csrf = login(client)
        page = client.get(f"/app/employees/{ids['worker']}/change-company")
        assert page.status_code == 200
        assert "Rectificar empresa" in page.text
        token = correction_token(page.text)
        response = client.post(
            f"/app/employees/{ids['worker']}/change-company",
            data=form_data(csrf, token, ids),
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text[:300]
        assert f"/app/employees/{ids['worker']}?company_corrected=1" == response.headers["location"]
        with SessionLocal() as db:
            worker = db.get(Employee, ids["worker"])
            assert worker.company_id == ids["destination"]
            assert worker.employee_code == 899002
            assert worker.admission_date == date(2024, 4, 1)
            assert worker.base_salary == 3044000
            assert worker.branch_id is None and worker.section_id is None
            assert db.scalar(select(SalaryHistory).where(SalaryHistory.employee_id == worker.id)) is not None
            events = list(db.scalars(select(EmployeeEvent).where(EmployeeEvent.employee_id == worker.id)))
            assert {e.event_type for e in events} == {"Alta", "Corrección administrativa"}


def test_existing_same_document_in_another_company_is_switchable_not_mergeable():
    with TestClient(app) as client, workforce(duplicate=True) as ids:
        csrf = login(client)
        page = client.get(f"/app/employees/{ids['worker']}/change-company")
        assert page.status_code == 200
        assert f"/app/employees/{ids['second']}" in page.text
        response = client.post(
            f"/app/employees/{ids['worker']}/change-company",
            data=form_data(csrf, correction_token(page.text), ids),
            follow_redirects=False,
        )
        assert response.status_code == 409
        assert "Ya existe un legajo" in response.text
        with SessionLocal() as db:
            assert db.get(Employee, ids["worker"]).company_id == ids["source"]
            assert db.get(Employee, ids["second"]).company_id == ids["destination"]
        listing = client.get(f"/app/employees?q={ids['document']}")
        assert listing.status_code == 200
        assert "2 empresas" in listing.text


def test_company_correction_refuses_dossiers_with_saved_payroll_calculations():
    with TestClient(app) as client, workforce(linked=True) as ids:
        csrf = login(client)
        page = client.get(f"/app/employees/{ids['worker']}/change-company")
        assert page.status_code == 200
        assert "Rectificación no disponible" in page.text
        assert 'name="correction_token"' not in page.text
        response = client.post(f"/app/employees/{ids['worker']}/change-company",
            data=form_data(csrf, "forged", ids), follow_redirects=False)
        assert response.status_code == 409
        with SessionLocal() as db:
            assert db.get(Employee, ids["worker"]).company_id == ids["source"]


def test_company_correction_rejects_expired_or_invalid_review_token():
    with TestClient(app) as client, workforce() as ids:
        csrf = login(client)
        response = client.post(f"/app/employees/{ids['worker']}/change-company",
            data=form_data(csrf, "invalid", ids), follow_redirects=False)
        assert response.status_code == 409
        with SessionLocal() as db:
            assert db.get(Employee, ids["worker"]).company_id == ids["source"]


def test_employee_exit_modal_is_in_body_not_in_page_title():
    with TestClient(app) as client, workforce() as ids:
        login(client)
        page = client.get(f"/app/employees/{ids['worker']}")
        assert page.status_code == 200
        assert "dossierExitModal" not in page.text.split("</title>", 1)[0]
        assert 'id="dossierExitModal"' in page.text
        assert f"/app/employees/{ids['worker']}/change-company" in page.text


def new_employment_token(html):
    found = re.search(r'name="new_employment_token" value="([^"]+)"', html)
    assert found, "New-employer flow did not provide an authenticated review token"
    return found.group(1)


def new_employment_data(csrf, token, ids, **overrides):
    data = {
        "csrf_token": csrf,
        "new_employment_token": token,
        "destination_company_id": str(ids["destination"]),
        "admission_date": "2026-10-30",
        "position": "Auxiliar de producción",
        "base_salary": "3044000",
        "payment_frequency": "Mensual",
        "contract_type": "Tiempo indefinido",
        "ips_contributor": "true",
        "employee_code": "899002",
        "acknowledgement": "new",
    }
    data.update(overrides)
    return data


def test_real_employer_change_creates_independent_history_and_draft_not_official_submission():
    with TestClient(app) as client, workforce(linked=True) as ids:
        csrf = login(client)
        page = client.get(f"/app/employees/{ids['worker']}/change-company")
        assert page.status_code == 200
        assert "Registrar nueva relación laboral" in page.text
        assert "El legajo anterior figura activo" in page.text
        token = new_employment_token(page.text)
        response = client.post(f"/app/employees/{ids['worker']}/new-employment",
            data=new_employment_data(csrf, token, ids), follow_redirects=False)
        assert response.status_code == 303, response.text[:400]
        match = re.search(r"/app/employees/(\d+)\?new_employment=1", response.headers["location"])
        assert match
        new_id = int(match.group(1))
        assert new_id != ids["worker"]
        with SessionLocal() as db:
            original = db.get(Employee, ids["worker"])
            new = db.get(Employee, new_id)
            assert original.company_id == ids["source"]
            assert original.status == "Activo"
            assert original.admission_date == date(2024, 4, 1)
            assert original.base_salary == 3044000
            assert new.company_id == ids["destination"]
            assert new.admission_date == date(2026, 10, 30)
            assert new.document_number == original.document_number
            assert new.position == "Auxiliar de producción"
            assert new.base_salary == 3044000
            assert list(db.scalars(select(CalculationRecord).where(
                CalculationRecord.employee_id == original.id
            )))
            assert not list(db.scalars(select(CalculationRecord).where(
                CalculationRecord.employee_id == new.id
            )))
            events = list(db.scalars(select(EmployeeEvent).where(EmployeeEvent.employee_id == new.id)))
            assert len(events) == 1 and events[0].event_type == "Alta"
            assert "historial del empleador anterior no se transfirió" in events[0].detail
            salary = db.scalar(select(SalaryHistory).where(SalaryHistory.employee_id == new.id))
            assert salary.new_salary == 3044000 and salary.previous_salary == 0
            drafts = list(db.scalars(select(ComplianceEvent).where(
                ComplianceEvent.employee_id == new.id
            )))
            assert {(event.authority, event.status) for event in drafts} == {
                ("REOP", "Borrador"), ("REI", "Borrador"),
            }
            assert all(event.submitted_at is None for event in drafts)


def test_new_employment_refuses_duplicate_in_target_and_keeps_existing_records():
    with TestClient(app) as client, workforce(duplicate=True) as ids:
        csrf = login(client)
        page = client.get(f"/app/employees/{ids['worker']}/change-company")
        response = client.post(f"/app/employees/{ids['worker']}/new-employment",
            data=new_employment_data(csrf, new_employment_token(page.text), ids),
            follow_redirects=False)
        assert response.status_code == 409
        assert "ya tiene un legajo" in response.text
        with SessionLocal() as db:
            assert db.get(Employee, ids["worker"]).company_id == ids["source"]
            assert db.get(Employee, ids["second"]).company_id == ids["destination"]
            count = len(list(db.scalars(select(Employee).where(
                Employee.company_id == ids["destination"],
                Employee.document_number == ids["document"],
            ))))
            assert count == 1


def test_new_employment_refuses_invalid_token_and_incomplete_approval():
    with TestClient(app) as client, workforce() as ids:
        csrf = login(client)
        url = f"/app/employees/{ids['worker']}/new-employment"
        data = new_employment_data(csrf, "invalid", ids)
        assert client.post(url, data=data, follow_redirects=False).status_code == 409
        page = client.get(f"/app/employees/{ids['worker']}/change-company")
        data = new_employment_data(csrf, new_employment_token(page.text), ids, acknowledgement="")
        assert client.post(url, data=data, follow_redirects=False).status_code == 422
        with SessionLocal() as db:
            assert not list(db.scalars(select(Employee).where(
                Employee.company_id == ids["destination"],
                Employee.document_number == ids["document"],
            )))


def test_new_employment_requires_new_salary_and_employer_specific_fields():
    with TestClient(app) as client, workforce() as ids:
        csrf = login(client)
        page = client.get(f"/app/employees/{ids['worker']}/change-company")
        url = f"/app/employees/{ids['worker']}/new-employment"
        token = new_employment_token(page.text)
        for change in (
            {"base_salary": "0"}, {"base_salary": "-200"},
            {"position": ""}, {"ips_contributor": "maybe"},
            {"admission_date": "1901-01-01"},
        ):
            response = client.post(url, data=new_employment_data(csrf, token, ids, **change),
                                   follow_redirects=False)
            assert response.status_code == 422, (change, response.status_code)
        with SessionLocal() as db:
            assert not list(db.scalars(select(Employee).where(
                Employee.company_id == ids["destination"],
                Employee.document_number == ids["document"],
            )))
