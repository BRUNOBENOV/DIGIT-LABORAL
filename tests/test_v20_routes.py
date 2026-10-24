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



def test_audit_filters_pagination_and_csv_export_are_scoped_to_studio():
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import AuditLog, User

    marker = "audit-filter-regression-20261023-unique"
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == "admin@digitlaboral.com.py"))
        assert admin is not None and admin.studio_id is not None
        db.add_all([
            AuditLog(
                studio_id=admin.studio_id, user_email="filter.actor@example.test",
                action="TEST_FILTER", entity="test_entity", entity_id="314159",
                detail=f"Detail contains {marker}",
            ),
            AuditLog(
                studio_id=admin.studio_id, user_email="other.actor@example.test",
                action="TEST_OTHER", entity="other_entity", entity_id="271828",
                detail="Different test detail",
            ),
        ])
        db.commit()

    with TestClient(app) as client:
        _login(client)
        filtered = client.get("/app/audit", params={"q": marker})
        assert filtered.status_code == 200
        assert marker in filtered.text
        assert "filter.actor@example.test" in filtered.text
        assert "other.actor@example.test" not in filtered.text
        by_action = client.get("/app/audit", params={"action": "TEST_FILTER", "entity": "test_entity"})
        assert by_action.status_code == 200
        assert "filter.actor@example.test" in by_action.text
        csv_response = client.get("/app/audit.csv", params={"q": marker})
        assert csv_response.status_code == 200
        assert "text/csv" in csv_response.headers.get("content-type", "")
        assert marker.encode("utf-8") in csv_response.content
        invalid_dates = client.get(
            "/app/audit", params={"start_date": "2026-10-24", "end_date": "2026-10-23"}
        )
        assert invalid_dates.status_code == 400
