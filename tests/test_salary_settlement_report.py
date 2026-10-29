from __future__ import annotations

import json
import re
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import AuditLog, CalculationRecord, Company, Employee, Studio, User, UserSecurity


def _login(client: TestClient, email: str = "admin@digitlaboral.com.py", password: str | None = None) -> None:
    page = client.get("/login")
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert page.status_code == 200 and match
    response = client.post(
        "/login",
        data={
            "email": email,
            "password": password or settings.demo_admin_password,
            "csrf_token": match.group(1),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _create_salary_record(*, company_id: int | None = None, employee_id: int | None = None):
    marker = f"salary-report-{uuid.uuid4().hex[:12]}"
    with SessionLocal() as db:
        company = db.get(Company, company_id) if company_id else db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        employee = db.get(Employee, employee_id) if employee_id else db.scalar(
            select(Employee).where(Employee.company_id == company.id).order_by(Employee.id)
        )
        assert employee is not None and employee.company_id == company.id
        result = {
            "kind": "salary",
            "title": "Liquidación de salario",
            "engine_version": "test",
            "identity": {
                "employer": company.legal_name,
                "ruc": company.ruc,
                "employee": employee.full_name,
                "ci": employee.document_number,
                "position": employee.position or "Auxiliar",
                "payment_method": "Transferencia",
            },
            "issued_date": "29/10/2026",
            "period": "2026-10",
            "earnings": [
                {"label": "Salario base", "amount": 2500000, "formula": "Base mensual", "legal": ""},
                {"label": "Horas extraordinarias", "amount": 200000, "formula": "Según horas registradas", "legal": "Art. 234"},
            ],
            "deductions": [
                {"label": "Aporte IPS trabajador", "amount": 243000, "formula": "Base de aporte revisada", "legal": ""},
            ],
            "gross": 2700000,
            "discounts": 243000,
            "net": 2457000,
            "net_label": "Neto a percibir",
            "warnings": [],
            "notes": marker,
            "partial": False,
        }
        item = CalculationRecord(
            company_id=company.id,
            employee_id=employee.id,
            calculation_type="suite_salary",
            reference_period="2026-10",
            input_json=json.dumps({"kind": "salary", **result["identity"], "month": "2026-10"}, ensure_ascii=False),
            result_json=json.dumps(result, ensure_ascii=False),
            amount=2457000,
            status="Aprobado",
            source="Centro laboral",
            notes=marker,
            created_by="test-salary-report",
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item.id, company.id, employee.id, marker


def test_salary_liquidation_report_shows_saved_records_and_filters():
    with TestClient(app) as client:
        _login(client)
        record_id, company_id, employee_id, marker = _create_salary_record()
        response = client.get(
            "/app/reports/liquidaciones-salarios",
            params={"company_id": company_id, "employee_id": employee_id, "period": "2026-10", "q": marker},
        )
        assert response.status_code == 200, response.text[:300]
        assert f"/app/reports/liquidaciones-salarios/{record_id}" in response.text
        assert "Liquidación de Salarios" in response.text
        assert "Gs. 2.457.000" in response.text
        assert "no inventa importes" in response.text.lower()


def test_salary_liquidation_detail_pdf_history_and_reprint_audit():
    with TestClient(app) as client:
        _login(client)
        record_id, company_id, employee_id, marker = _create_salary_record()
        detail = client.get(f"/app/reports/liquidaciones-salarios/{record_id}")
        assert detail.status_code == 200, detail.text[:300]
        for expected in (
            "DATOS DEL EMPLEADOR", "DATOS DEL FUNCIONARIO Y PERÍODO",
            "Salario base", "Horas extraordinarias", "Aporte IPS trabajador",
            "NETO A COBRAR", "Firma del empleador", "Firma del funcionario",
            "No es un formulario oficial",
        ):
            assert expected.lower() in detail.text.lower(), expected

        pdf = client.get(f"/app/reports/liquidaciones-salarios/{record_id}/pdf")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"].startswith("application/pdf")
        assert pdf.content.startswith(b"%PDF")

        token = re.search(r'name="csrf_token" value="([^"]+)"', detail.text)
        assert token
        printed = client.post(
            f"/app/reports/liquidaciones-salarios/{record_id}/reimprimir",
            data={"csrf_token": token.group(1)},
            follow_redirects=False,
        )
        assert printed.status_code == 303
        assert printed.headers["location"].endswith(f"/app/reports/liquidaciones-salarios/{record_id}?imprimir=1")

        with SessionLocal() as db:
            events = list(db.scalars(select(AuditLog).where(
                AuditLog.entity == "liquidacion_salario",
                AuditLog.entity_id == str(record_id),
                AuditLog.action.in_(("reimpresion_pdf_liquidacion_salario", "reimpresion_liquidacion_salario")),
            )))
            assert len(events) >= 2


def test_company_user_cannot_open_another_company_salary_receipt():
    with SessionLocal() as db:
        studio = db.scalar(select(Studio).order_by(Studio.id))
        assert studio is not None
        own_company = db.scalar(select(Company).where(Company.studio_id == studio.id).order_by(Company.id))
        assert own_company is not None
        own_employee = db.scalar(select(Employee).where(Employee.company_id == own_company.id).order_by(Employee.id))
        assert own_employee is not None
        other_company = Company(
            studio_id=studio.id,
            legal_name=f"Empresa ajena {uuid.uuid4().hex[:6]}",
            ruc=f"99{uuid.uuid4().int % 10**7:07d}-{uuid.uuid4().int % 10}",
            address="Dirección de prueba",
            city="Ciudad del Este",
        )
        db.add(other_company)
        db.flush()
        other_employee = Employee(
            company_id=other_company.id,
            full_name="Funcionario de otra empresa",
            document_number=f"TEST-{uuid.uuid4().hex[:10]}",
            position="Auxiliar",
        )
        db.add(other_employee)
        db.flush()
        user = User(
            studio_id=studio.id,
            company_id=own_company.id,
            full_name="Usuario de empresa - informe salarial",
            email=f"salary-report-company-{uuid.uuid4().hex[:10]}@persona.test",
            password_hash=hash_password("Company-Salary-2026!"),
            role="empresa",
            active=True,
            must_change_password=False,
        )
        db.add(user)
        db.flush()
        db.add(UserSecurity(user_id=user.id))
        db.commit()
        other_company_id, other_employee_id = other_company.id, other_employee.id
        user_email = user.email

    record_id, _, _, _ = _create_salary_record(company_id=other_company_id, employee_id=other_employee_id)
    with TestClient(app) as client:
        _login(client, user_email, "Company-Salary-2026!")
        response = client.get(f"/app/reports/liquidaciones-salarios/{record_id}")
        assert response.status_code == 404
        listing = client.get(
            "/app/reports/liquidaciones-salarios",
            params={"company_id": other_company_id, "employee_id": other_employee_id},
        )
        assert listing.status_code == 404
