from __future__ import annotations

import re
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app.config import settings

from app.main import app


def _login(client: TestClient) -> str:
    page = client.get("/login")
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert page.status_code == 200 and match
    response = client.post(
        "/login",
        data={"email": "admin@digitlaboral.com.py", "password": settings.demo_admin_password, "csrf_token": match.group(1)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    dashboard = client.get("/app")
    dashboard_token = re.search(r'name="csrf_token" value="([^"]+)"', dashboard.text)
    assert dashboard.status_code == 200 and dashboard_token
    return dashboard_token.group(1)


def test_critical_authenticated_pages_render_html():
    paths = (
        "/app",
        "/app/companies",
        "/app/employees",
        "/app/requests",
        "/app/payrolls",
        "/app/vacations",
        "/app/aguinaldo",
        "/app/documents",
        "/app/certificates",
        "/app/reports",
        "/app/calendar",
        "/app/compliance",
        "/app/labor-code",
        "/app/users",
        "/app/audit",
        "/app/security",
    )
    with TestClient(app) as client:
        _login(client)
        for path in paths:
            response = client.get(path)
            assert response.status_code == 200, path
            assert "text/html" in response.headers.get("content-type", ""), path
            assert "Digit Laboral" in response.text, path
            assert not response.text.lstrip().startswith('{"detail"'), path


def test_post_forms_include_csrf_tokens():
    with TestClient(app) as client:
        _login(client)
        for path in ("/app/companies", "/app/employees", "/app/users", "/app/compliance", "/app/security"):
            response = client.get(path)
            soup = BeautifulSoup(response.text, "html.parser")
            post_forms = [form for form in soup.find_all("form") if (form.get("method") or "get").lower() == "post"]
            assert post_forms, path
            for form in post_forms:
                token = form.find("input", attrs={"name": "csrf_token"})
                assert token is not None, f"{path}: formulario POST sin CSRF"
                assert token.get("value"), f"{path}: token CSRF vacío"


def test_friendly_html_error_page_replaces_raw_json():
    with TestClient(app) as client:
        _login(client)
        response = client.get("/app/companies/999999999")
        assert response.status_code == 404
        assert "No se pudo completar la operación" in response.text
        assert "application/json" not in response.headers.get("content-type", "")
        assert response.headers.get("x-request-id")


def test_branch_compliance_profile_can_be_saved():
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import Branch, BranchComplianceProfile, Company

    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        branch = db.scalar(select(Branch).where(Branch.company_id == company.id).order_by(Branch.id))
        assert branch is not None
        company_id = company.id
        branch_id = branch.id

    with TestClient(app) as client:
        csrf = _login(client)
        response = client.post(
            "/app/compliance/branch-profile",
            data={
                "csrf_token": csrf,
                "company_id": str(company_id),
                "branch_id": str(branch_id),
                "ips_employer_number": "IPS-TEST-001",
                "mtess_employer_number": "MTESS-TEST-001",
                "department": "Alto Paraná",
                "district": "Ciudad del Este",
                "locality": "Centro",
                "economic_activity": "Servicios contables",
                "activity_code": "TEST",
                "establishment_type": "Sucursal",
                "rei_status": "Verificado",
                "reop_status": "Verificado",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].endswith("saved=branch")

    with SessionLocal() as db:
        profile = db.scalar(select(BranchComplianceProfile).where(BranchComplianceProfile.branch_id == branch_id))
        assert profile is not None
        assert profile.ips_employer_number == "IPS-TEST-001"
        assert profile.mtess_employer_number == "MTESS-TEST-001"



def test_company_logo_presentation_preferences_are_saved_and_bounded():
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import Company, CompanyBranding

    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        company_id = company.id

    with TestClient(app) as client:
        csrf = _login(client)
        saved = client.post(
            f"/app/companies/{company_id}/branding",
            data={
                "csrf_token": csrf,
                "logo_fit": "cover",
                "logo_scale": "120",
                "logo_alignment": "right",
                "logo_background": "navy",
                "primary_color": "#112233",
                "secondary_color": "#445566",
                "document_footer": "Pie personalizado de prueba",
                "signature_name": "Representante de prueba",
                "signature_title": "Representante legal",
                "document_prefix": "DLTEST",
                "show_ruc": "on",
                "show_contact": "on",
            },
            follow_redirects=False,
        )
        assert saved.status_code == 303

    with SessionLocal() as db:
        branding = db.scalar(select(CompanyBranding).where(CompanyBranding.company_id == company_id))
        assert branding is not None
        assert branding.logo_fit == "cover"
        assert branding.logo_scale == 120
        assert branding.logo_alignment == "right"
        assert branding.logo_background == "navy"

    with TestClient(app) as client:
        csrf = _login(client)
        invalid = client.post(
            f"/app/companies/{company_id}/branding",
            data={
                "csrf_token": csrf,
                "logo_fit": "invalid",
                "logo_scale": "999",
                "logo_alignment": "outside",
                "logo_background": "purple",
            },
            follow_redirects=False,
        )
        assert invalid.status_code == 303

    with SessionLocal() as db:
        branding = db.scalar(select(CompanyBranding).where(CompanyBranding.company_id == company_id))
        assert branding is not None
        assert branding.logo_fit == "contain"
        assert branding.logo_scale == 140
        assert branding.logo_alignment == "center"
        assert branding.logo_background == "white"



def test_saved_calculators_use_commercial_half_up_rounding():
    import json
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import CalculationRecord, Company

    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        company_id = company.id

    cases = [
        {
            "calculation_type": "hours",
            "reference_period": "round-hours",
            "salary": "1",
            "monthly_hours": "2",
            "hours_quantity": "1",
            "multiplier": "1",
            "expected_amount": 1,
            "expected_result": {"hour_value": 1, "total": 1},
        },
        {
            "calculation_type": "aguinaldo",
            "reference_period": "round-aguinaldo",
            "total_remunerations": "6",
            "expected_amount": 1,
            "expected_result": {
                "aguinaldo": 1,
                "total_remunerations": 6,
                "legal_basis": "Código del Trabajo, arts. 243 y 244",
            },
        },
    ]

    with TestClient(app) as client:
        csrf = _login(client)
        for case in cases:
            data = {
                "csrf_token": csrf,
                "calculation_type": case["calculation_type"],
                "company_id": str(company_id),
                "employee_id": "",
                "reference_period": case["reference_period"],
                "salary": case.get("salary", ""),
                "monthly_hours": case.get("monthly_hours", ""),
                "hours_quantity": case.get("hours_quantity", ""),
                "multiplier": case.get("multiplier", ""),
                "total_remunerations": case.get("total_remunerations", ""),
                "gross": "",
                "other_income": "",
                "other_discount": "",
                "ips_base": "",
            }
            response = client.post("/app/calculations", data=data, follow_redirects=False)
            assert response.status_code == 303, response.text

            with SessionLocal() as db:
                item = db.scalar(
                    select(CalculationRecord)
                    .where(
                        CalculationRecord.company_id == company_id,
                        CalculationRecord.calculation_type == case["calculation_type"],
                        CalculationRecord.reference_period == case["reference_period"],
                    )
                    .order_by(CalculationRecord.id.desc())
                )
                assert item is not None
                assert item.amount == case["expected_amount"]
                assert json.loads(item.result_json) == case["expected_result"]
