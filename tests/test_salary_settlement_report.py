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
from app.models import (
    AuditLog, BranchComplianceProfile, CalculationRecord, Company, CompanyComplianceProfile,
    Employee, EmployeeComplianceProfile, IntegrationBatch, Studio, User, UserSecurity,
)


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


def _verify_reop_profiles(company_id: int, employee_id: int, patronal_number: str) -> None:
    with SessionLocal() as db:
        company = db.get(Company, company_id)
        employee = db.get(Employee, employee_id)
        assert company is not None and employee is not None
        company.mtess_employer_number = patronal_number

        company_profile = db.scalar(
            select(CompanyComplianceProfile).where(CompanyComplianceProfile.company_id == company_id)
        )
        if not company_profile:
            company_profile = CompanyComplianceProfile(company_id=company_id)
            db.add(company_profile)
        company_profile.department = "Alto Paraná"
        company_profile.district = "Ciudad del Este"
        company_profile.locality = "Ciudad del Este"
        company_profile.economic_activity = "Servicios profesionales"
        company_profile.reop_status = "Verificado"

        employee_profile = db.scalar(
            select(EmployeeComplianceProfile).where(EmployeeComplianceProfile.employee_id == employee_id)
        )
        if not employee_profile:
            employee_profile = EmployeeComplianceProfile(employee_id=employee_id)
            db.add(employee_profile)
        employee_profile.sex = "Masculino"
        employee_profile.nationality = "Paraguaya"
        employee_profile.marital_status = "Soltero"
        employee_profile.occupation_code = "OCUP-TEST"
        employee_profile.reop_status = "Verificado"

        if employee.branch_id:
            branch_profile = db.scalar(
                select(BranchComplianceProfile).where(BranchComplianceProfile.branch_id == employee.branch_id)
            )
            if not branch_profile:
                branch_profile = BranchComplianceProfile(branch_id=employee.branch_id)
                db.add(branch_profile)
            branch_profile.mtess_employer_number = patronal_number
            branch_profile.department = "Alto Paraná"
            branch_profile.district = "Ciudad del Este"
            branch_profile.locality = "Ciudad del Este"
            branch_profile.economic_activity = "Servicios profesionales"
            branch_profile.reop_status = "Verificado"
        db.commit()


def test_existing_report_center_entry_opens_enhanced_salary_report_without_duplicate_navigation():
    with TestClient(app) as client:
        _login(client)
        catalog = client.get("/app/reports")
        assert catalog.status_code == 200, catalog.text[:300]
        assert 'href="/app/reports/liquidacion-salario"' in catalog.text
        assert "Liquidación de Salarios" in catalog.text
        assert catalog.text.count("Liquidación de Salarios") == 1
        assert "INFORME DEDICADO" not in catalog.text
        assert 'href="/app/reports/liquidaciones-salarios"' not in catalog.text

        legacy_entry = client.get(
            "/app/reports/liquidacion-salario?period=2026-10",
            follow_redirects=False,
        )
        assert legacy_entry.status_code == 303
        assert legacy_entry.headers["location"] == "/app/reports/liquidaciones-salarios?period=2026-10"


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
        assert "origen: módulo cálculo" in response.text.lower()


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


def test_reop_salary_handoff_validation_submission_and_official_receipt_archive():
    with TestClient(app) as client:
        _login(client)
        record_id, company_id, employee_id, _marker = _create_salary_record()
        _verify_reop_profiles(company_id, employee_id, "MTESS-TEST-01")

        detail = client.get(f"/app/reports/liquidaciones-salarios/{record_id}")
        assert detail.status_code == 200, detail.text[:300]
        token = re.search(r'name="csrf_token" value="([^"]+)"', detail.text)
        assert token

        prepared = client.post(
            f"/app/reports/liquidaciones-salarios/{record_id}/reop/prepare",
            data={
                "csrf_token": token.group(1),
                "payment_date": "2026-10-31",
                "payment_method": "Transferencia",
                "days_worked": "30",
                "hours_worked": "240",
                "pieces_or_tasks": "No aplica",
            },
            follow_redirects=False,
        )
        assert prepared.status_code == 303, prepared.text[:300]
        assert "reop_batch=" in prepared.headers["location"]
        batch_match = re.search(r"reop_batch=(\d+)", prepared.headers["location"])
        assert batch_match
        batch_id = int(batch_match.group(1))

        with SessionLocal() as db:
            batch = db.get(IntegrationBatch, batch_id)
            assert batch is not None
            assert batch.authority == "REOP"
            assert batch.calculation_record_id == record_id
            assert batch.status == "Generado"
            assert batch.file_sha256 and len(batch.file_sha256) == 64
            assert batch.file_bytes and batch.file_bytes.startswith(b"PK")
            assert '"integration_mode":"manual_assisted"' in batch.payload_json
            assert batch.error_message == ""

        validated = client.post(
            f"/app/reports/liquidaciones-salarios/{record_id}/reop/{batch_id}/validate",
            data={"csrf_token": token.group(1)},
            follow_redirects=False,
        )
        assert validated.status_code == 303
        with SessionLocal() as db:
            batch = db.get(IntegrationBatch, batch_id)
            assert batch is not None and batch.status == "Validado"
            assert batch.approved_by == "admin@digitlaboral.com.py"

        submitted = client.post(
            f"/app/compliance/batches/{batch_id}/receipt",
            data={
                "csrf_token": token.group(1),
                "status": "Presentado",
                "external_reference": "REOP-TEST-123",
            },
            follow_redirects=False,
        )
        assert submitted.status_code == 303
        assert f"/app/reports/liquidaciones-salarios/{record_id}" in submitted.headers["location"]

        fake_pdf = b"%PDF-1.4\nSynthetic test receipt fixture\n%%EOF"
        accepted = client.post(
            f"/app/compliance/batches/{batch_id}/receipt",
            data={
                "csrf_token": token.group(1),
                "status": "Aceptado",
                "external_reference": "REOP-TEST-123",
            },
            files={"receipt": ("reop-test.pdf", fake_pdf, "application/pdf")},
            follow_redirects=False,
        )
        assert accepted.status_code == 303
        with SessionLocal() as db:
            batch = db.get(IntegrationBatch, batch_id)
            assert batch is not None and batch.status == "Aceptado"
            assert bytes(batch.receipt_bytes or b"") == fake_pdf
            assert batch.external_reference == "REOP-TEST-123"
        final_detail = client.get(f"/app/reports/liquidaciones-salarios/{record_id}")
        assert final_detail.status_code == 200
        assert "Intentos y comprobantes" in final_detail.text
        assert "REOP-TEST-123" in final_detail.text
        assert "no se verifica automáticamente" in final_detail.text.lower()
        assert f"/app/compliance/batches/{batch_id}/receipt" in final_detail.text


def test_reop_salary_handoff_blocks_validation_when_required_data_is_missing():
    with TestClient(app) as client:
        _login(client)
        record_id, company_id, _employee_id, _marker = _create_salary_record()
        _verify_reop_profiles(company_id, _employee_id, "MTESS-TEST-02")

        detail = client.get(f"/app/reports/liquidaciones-salarios/{record_id}")
        token = re.search(r'name="csrf_token" value="([^"]+)"', detail.text)
        assert token
        prepared = client.post(
            f"/app/reports/liquidaciones-salarios/{record_id}/reop/prepare",
            data={
                "csrf_token": token.group(1),
                "payment_date": "",
                "payment_method": "",
                "days_worked": "",
                "hours_worked": "",
                "pieces_or_tasks": "",
            },
            follow_redirects=False,
        )
        assert prepared.status_code == 303
        match = re.search(r"reop_batch=(\d+)", prepared.headers["location"])
        assert match
        batch_id = int(match.group(1))
        with SessionLocal() as db:
            batch = db.get(IntegrationBatch, batch_id)
            assert batch is not None and batch.status == "Generado"
            assert "Fecha de pago" in batch.error_message
            assert "Horas trabajadas" in batch.error_message
        validation = client.post(
            f"/app/reports/liquidaciones-salarios/{record_id}/reop/{batch_id}/validate",
            data={"csrf_token": token.group(1)},
            follow_redirects=False,
        )
        assert validation.status_code == 303
        assert "reop_validation_error=1" in validation.headers["location"]
        with SessionLocal() as db:
            batch = db.get(IntegrationBatch, batch_id)
            assert batch is not None and batch.status == "Generado"
            assert "Cantidad de días trabajados" in batch.error_message


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
