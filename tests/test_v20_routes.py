from __future__ import annotations

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app.main import app


def _login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"email": "admin@digitlaboral.com.py", "password": "demo123"},
        follow_redirects=False,
    )
    assert response.status_code == 303


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
        _login(client)
        response = client.post(
            "/app/compliance/branch-profile",
            data={
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
