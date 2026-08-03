from __future__ import annotations

import io

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ai_service import generate_assistance
from app.database import SessionLocal
from app.main import app
from app.models import CalculationRecord, Company, CompanyBranding, Employee


def login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"email": "admin@digitlaboral.com.py", "password": "demo123"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_new_automation_pages_render():
    with TestClient(app) as client:
        login(client)
        for path, marker in (
            ("/app/reports", "Informes"),
            ("/app/ai", "Asistente IA"),
            ("/app/calculations", "Centro de cálculos"),
            ("/app/certificates", "Documentos laborales"),
        ):
            response = client.get(path)
            assert response.status_code == 200
            assert marker in response.text


def test_saved_calculation_can_be_linked_to_certificate():
    with TestClient(app) as client:
        login(client)
        with SessionLocal() as db:
            company = db.scalar(select(Company).order_by(Company.id))
            employee = db.scalar(select(Employee).where(Employee.company_id == company.id).order_by(Employee.id))
        response = client.post(
            "/app/calculations",
            data={
                "calculation_type": "aguinaldo",
                "company_id": str(company.id),
                "employee_id": str(employee.id),
                "reference_period": "2026",
                "total_remunerations": "36000000",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        with SessionLocal() as db:
            item = db.scalar(select(CalculationRecord).order_by(CalculationRecord.id.desc()))
            assert item.amount == 3_000_000
        linked = client.get(f"/app/calculations/{item.id}/certificate", follow_redirects=False)
        assert linked.status_code == 307 or linked.status_code == 303
        assert "calculation_id=" in linked.headers["location"]


def test_company_logo_upload_and_retrieval():
    png = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    with TestClient(app) as client:
        login(client)
        with SessionLocal() as db:
            company = db.scalar(select(Company).order_by(Company.id))
        response = client.post(
            f"/app/companies/{company.id}/branding",
            data={
                "primary_color": "#173B86",
                "secondary_color": "#0B1F48",
                "document_footer": "Documento automatizado",
                "signature_name": "Representante Demo",
                "signature_title": "Representante legal",
                "document_prefix": "CP",
                "show_ruc": "on",
                "show_contact": "on",
            },
            files={"logo": ("logo.png", io.BytesIO(png), "image/png")},
            follow_redirects=False,
        )
        assert response.status_code == 303
        logo = client.get(f"/app/companies/{company.id}/logo")
        assert logo.status_code == 200
        assert logo.headers["content-type"].startswith("image/png")
        with SessionLocal() as db:
            branding = db.scalar(select(CompanyBranding).where(CompanyBranding.company_id == company.id))
            assert branding.logo_bytes
            assert branding.document_prefix == "CP"


def test_ai_fallback_does_not_require_external_api():
    result = generate_assistance(
        purpose="control",
        context={"company": {"legal_name": "Demo", "ruc": ""}, "employee": {}, "calculations": []},
        instruction="Revisar datos faltantes",
        allow_external=False,
    )
    assert result.used_external_ai is False
    assert "Revisión automática" in result.text
    assert "requiere revisión" in result.text
