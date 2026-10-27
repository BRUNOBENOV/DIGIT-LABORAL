from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def _login(client: TestClient) -> None:
    login_page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text)
    assert login_page.status_code == 200 and token
    response = client.post(
        "/login",
        data={
            "email": "admin@digitlaboral.com.py",
            "password": settings.demo_admin_password,
            "csrf_token": token.group(1),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_global_context_selector_is_available_after_login():
    with TestClient(app) as client:
        _login(client)
        response = client.get("/app")
        assert response.status_code == 200
        assert 'data-labor-context' in response.text
        assert 'action="/app/context"' in response.text
        assert "Contexto de trabajo" in response.text


def test_context_employee_endpoint_requires_an_authenticated_session():
    with TestClient(app) as client:
        response = client.get("/app/context/employees?company_id=1", follow_redirects=False)
        assert response.status_code in {302, 303, 307, 401, 403}


def test_context_persists_company_and_employee_across_modules():
    with TestClient(app) as client:
        _login(client)
        companies_page = client.get("/app/companies")
        assert companies_page.status_code == 200
        company_match = re.search(r'<option value="(\\d+)"', companies_page.text)
        assert company_match, "La base de prueba debe incluir al menos una empresa."
        company_id = int(company_match.group(1))

        response = client.get(f"/app/context/employees?company_id={company_id}")
        assert response.status_code == 200
        employee_rows = response.json()
        if not employee_rows:
            # Seed data without employees still tests persistence of the company.
            employee_id = None
        else:
            employee_id = int(employee_rows[0]["id"])

        app_page = client.get("/app")
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', app_page.text)
        assert csrf_match
        data = {
            "company_id": str(company_id),
            "employee_id": str(employee_id or ""),
            "return_to": "/app",
            "csrf_token": csrf_match.group(1),
        }
        saved = client.post("/app/context", data=data, follow_redirects=False)
        assert saved.status_code == 303

        response = client.get("/app/calculations?tipo=salary")
        assert response.status_code == 200
        assert f'value="{company_id}" selected' in response.text
        if employee_id:
            assert f'value="{employee_id}" data-company="{company_id}" selected' in response.text
            liquidation = client.get("/app/liquidaciones?tipo=settlement")
            assert liquidation.status_code == 200
            assert f'name="employee_id"' in liquidation.text
            assert str(employee_id) in liquidation.text


def test_context_rejects_external_return_url():
    with TestClient(app) as client:
        _login(client)
        app_page = client.get("/app")
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', app_page.text)
        assert csrf_match
        response = client.post(
            "/app/context",
            data={"return_to": "https://example.invalid/", "csrf_token": csrf_match.group(1)},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/app"
