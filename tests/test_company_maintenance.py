from __future__ import annotations

import re
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.main import app, normalize_company_ruc
from app.models import Company


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
    token = re.search(r'name="csrf_token" value="([^"]+)"', dashboard.text)
    assert dashboard.status_code == 200 and token
    return token.group(1)


def test_ruc_normalization_checks_numeric_length_and_standardizes_display():
    assert normalize_company_ruc("80012345-6") == "80012345-6"
    assert normalize_company_ruc("80.012.345 6") == "80012345-6"
    assert normalize_company_ruc("ABC-123") is None
    assert normalize_company_ruc("123") is None


def test_company_form_contains_required_maintenance_fields_and_paraguayan_selectors():
    with TestClient(app) as client:
        _login(client)
        response = client.get("/app/companies")
        assert response.status_code == 200
        for field in (
            'name="company_code"', 'name="legal_name"', 'name="owner_name"',
            'name="legal_representative"', 'name="address"', 'name="city"',
            'name="department"', 'name="work_sector"', 'name="work_location"',
            'name="economic_activity"', 'name="phone"', 'name="contact_name"',
            'name="ips_employer_number"', 'name="mtess_employer_number"', 'name="ruc"',
            'name="legal_representative_document"',
        ):
            assert field in response.text
        assert 'aria-live="polite"' in response.text
        assert "Ciudad del Este" in response.text
        assert "Alto Paraná" in response.text


def test_api_lookup_by_existing_company_code_returns_record_for_authenticated_study():
    with SessionLocal() as db:
        company = db.scalar(
            select(Company).where(Company.company_code.is_not(None), Company.status != "Archivada").order_by(Company.id)
        )
        assert company is not None, "The migration should backfill a code for existing companies."
        code = company.company_code
        company_id = company.id
    with TestClient(app) as client:
        _login(client)
        response = client.get(f"/api/companies/by-code/{code}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == company_id
        assert payload["company_code"] == code
        assert payload["legal_name"]
        assert "department" in payload
        assert "economic_activity" in payload


def test_api_company_list_requires_authentication():
    with TestClient(app) as client:
        response = client.get("/api/companies", follow_redirects=False)
        assert response.status_code in {302, 303}
