from __future__ import annotations

import re
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.main import app, normalize_company_ruc, ruc_check_digit
from app.models import AuditLog, Branch, Company, CompanyBranding, CompanyComplianceProfile, User
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
    assert normalize_company_ruc("80000519-8") == "80000519-8"
    assert normalize_company_ruc("80.000.519 8") == "80000519-8"
    assert normalize_company_ruc("80000519-9") is None
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


def test_api_company_crud_creates_updates_and_archives_with_csrf():
    company_id = None
    with SessionLocal() as db:
        studio_id = db.scalar(select(User.studio_id).where(User.email == "admin@digitlaboral.com.py"))
        assert studio_id is not None
        maximum = db.scalar(select(__import__("sqlalchemy").func.max(Company.company_code)).where(Company.studio_id == studio_id)) or 0
    code = int(maximum) + int(uuid.uuid4().int % 100_000) + 1
    ruc_base = str(80_000_000 + int(uuid.uuid4().int % 9_999_999))
    ruc = f"{ruc_base}-{ruc_check_digit(ruc_base)}"
    payload = {
        "company_code": code,
        "legal_name": "Empresa CRUD QA",
        "trade_name": "CRUD QA",
        "ruc": ruc,
        "owner_name": "Propietario QA",
        "legal_representative": "Representante QA",
        "address": "Dirección de prueba",
        "city": "Ciudad del Este",
        "department": "Alto Paraná",
        "work_sector": "Administración",
        "work_location": "Casa central",
        "economic_activity": "Pruebas automatizadas",
        "phone": "061500000",
        "contact_name": "Contacto QA",
        "email": "qa@example.invalid",
        "ips_employer_number": "123456",
        "mtess_employer_number": "654321",
        "legal_representative_document": "1234567",
    }
    try:
        with TestClient(app) as client:
            csrf = _login(client)
            headers = {"X-CSRF-Token": csrf, "Accept": "application/json"}
            created = client.post("/api/companies", json=payload, headers=headers)
            assert created.status_code == 201, created.text
            stored = created.json()
            company_id = stored["id"]
            assert stored["company_code"] == code
            assert stored["ruc"] == ruc
            assert stored["owner_name"] == "Propietario QA"
            assert stored["department"] == "Alto Paraná"

            updated = client.put(
                f"/api/companies/{company_id}",
                json={"legal_name": "Empresa CRUD QA actualizada", "work_sector": "Ventas"},
                headers=headers,
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["legal_name"] == "Empresa CRUD QA actualizada"
            assert updated.json()["work_sector"] == "Ventas"

            archived = client.delete(f"/api/companies/{company_id}", headers=headers)
            assert archived.status_code == 200, archived.text
            assert archived.json()["status"] == "Archivada"
            assert client.get(f"/api/companies/by-code/{code}").status_code == 404
            all_companies = client.get("/api/companies?include_archived=true")
            assert all_companies.status_code == 200
            assert any(item["id"] == company_id and item["status"] == "Archivada" for item in all_companies.json()["items"])
    finally:
        if company_id is not None:
            with SessionLocal() as db:
                profile = db.scalar(select(CompanyComplianceProfile).where(CompanyComplianceProfile.company_id == company_id))
                if profile:
                    db.delete(profile)
                brand = db.scalar(select(CompanyBranding).where(CompanyBranding.company_id == company_id))
                if brand:
                    db.delete(brand)
                for branch in db.scalars(select(Branch).where(Branch.company_id == company_id)).all():
                    db.delete(branch)
                for entry in db.scalars(select(AuditLog).where(AuditLog.entity == "empresa", AuditLog.entity_id == str(company_id))).all():
                    db.delete(entry)
                company = db.get(Company, company_id)
                if company:
                    db.delete(company)
                db.commit()


def test_api_company_list_requires_authentication():
    with TestClient(app) as client:
        response = client.get("/api/companies", follow_redirects=False)
        assert response.status_code in {302, 303}
