from __future__ import annotations

import re
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.database import SessionLocal
from app.main import app
from app.models import Company, Studio, User, UserSecurity


def _create_company_user() -> tuple[str, str, int]:
    email = f"company-report-{uuid.uuid4().hex[:12]}@persona.test"
    password = "Company-Report-2026!"
    with SessionLocal() as db:
        studio = db.scalar(select(Studio).order_by(Studio.id))
        assert studio is not None
        company = db.scalar(
            select(Company).where(Company.studio_id == studio.id).order_by(Company.id)
        )
        assert company is not None
        user = User(
            studio_id=studio.id,
            company_id=company.id,
            full_name="Persona empresa - Informes",
            email=email,
            password_hash=hash_password(password),
            role="empresa",
            active=True,
            must_change_password=False,
        )
        db.add(user)
        db.flush()
        db.add(UserSecurity(user_id=user.id))
        db.commit()
        return email, password, company.id


def _login(client: TestClient, email: str, password: str) -> None:
    page = client.get("/login")
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert page.status_code == 200 and match
    response = client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": match.group(1)},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_company_role_sees_scoped_report_catalog_but_not_medical_or_compliance_links():
    with TestClient(app) as client:
        email, password, company_id = _create_company_user()
        _login(client, email, password)

        home = client.get("/app")
        assert home.status_code == 200
        assert "Centro de informes" in home.text
        assert 'href="/app/compliance"' not in home.text
        assert 'href="/app/audit"' not in home.text

        page = client.get("/app/reports")
        assert page.status_code == 200
        assert "Informes de mi empresa" in page.text
        assert "Listado Empresa" in page.text
        assert "Listado Empleado" in page.text
        assert "Listado Examen Médico" not in page.text

        catalog = client.get("/api/reports/catalog")
        assert catalog.status_code == 200
        payload = catalog.json()
        keys = [report["key"] for group in payload["groups"] for report in group["reports"]]
        assert payload["total"] == len(keys) == 34
        assert "listado-examen-medico" not in keys

        report = client.get("/api/reports/listado-empresa")
        assert report.status_code == 200
        assert all(row["Código"] or row["Empresa"] for row in report.json()["records"])
        assert report.json()["total"] >= 0
