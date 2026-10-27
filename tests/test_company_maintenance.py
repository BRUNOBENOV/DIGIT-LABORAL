from __future__ import annotations

import re
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.main import app, normalize_company_ruc
from app.models import Company, CompanyComplianceProfile, User
from app.paraguay_locations import PARAGUAY_CITIES, PARAGUAY_CITY_NAMES, PARAGUAY_DEPARTMENTS


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


def test_paraguay_city_catalog_has_262_unique_municipalities_and_valid_departments():
    assert len(PARAGUAY_CITIES) == 262
    assert len(PARAGUAY_CITY_NAMES) == len(PARAGUAY_CITIES)
    assert len(PARAGUAY_DEPARTMENTS) == 18
    assert all(item["department"] in PARAGUAY_DEPARTMENTS for item in PARAGUAY_CITIES)
    assert any(item["name"] == "Ciudad del Este" and item["department"] == "Alto Paraná" for item in PARAGUAY_CITIES)


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
    code = int(uuid.uuid4().int % 1_000_000_000) + 1
    ruc = str(int(uuid.uuid4().int % 900_000_000) + 100_000_000)
    with SessionLocal() as db:
        studio_id = db.scalar(select(User.studio_id).where(User.email == "admin@digitlaboral.com.py"))
        assert studio_id is not None
        company = Company(
            studio_id=studio_id, company_code=code, legal_name="Empresa temporal QA",
            ruc=f"{ruc[:-1]}-{ruc[-1]}", city="Ciudad del Este", status="Activa",
        )
        db.add(company)
        db.flush()
        db.add(CompanyComplianceProfile(
            company_id=company.id, department="Alto Paraná",
            economic_activity="Registro temporal de prueba",
        ))
        db.commit()
        company_id = company.id
    try:
        with TestClient(app) as client:
            _login(client)
            response = client.get(f"/api/companies/by-code/{code}")
            assert response.status_code == 200
            payload = response.json()
            assert payload["id"] == company_id
            assert payload["company_code"] == code
            assert payload["legal_name"] == "Empresa temporal QA"
            assert payload["department"] == "Alto Paraná"
            assert payload["economic_activity"] == "Registro temporal de prueba"
    finally:
        with SessionLocal() as db:
            profile = db.scalar(select(CompanyComplianceProfile).where(CompanyComplianceProfile.company_id == company_id))
            if profile:
                db.delete(profile)
            company = db.get(Company, company_id)
            if company:
                db.delete(company)
            db.commit()


def test_api_company_list_requires_authentication():
    with TestClient(app) as client:
        response = client.get("/api/companies", follow_redirects=False)
        assert response.status_code in {302, 303}
