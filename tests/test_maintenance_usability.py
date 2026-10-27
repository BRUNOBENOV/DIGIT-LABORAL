from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


ROOT = Path(__file__).resolve().parents[1]


def _login(client: TestClient) -> None:
    page = client.get("/login")
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert page.status_code == 200 and match
    response = client.post(
        "/login",
        data={
            "email": "admin@digitlaboral.com.py",
            "password": settings.demo_admin_password,
            "csrf_token": match.group(1),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_company_directory_has_secondary_navigation_quick_filters_and_sorting():
    with TestClient(app) as client:
        _login(client)
        response = client.get("/app/companies")
        assert response.status_code == 200
        for expected in (
            'aria-label="Subsecciones de mantenimiento"',
            'aria-current="page">Empresas',
            'data-company-directory',
            'data-company-filter="active"',
            'data-company-filter="archived"',
            'data-company-filter="no-logo"',
            'id="companySort"',
            'id="companyQuickEmpty"',
        ):
            assert expected in response.text


def test_employee_directory_has_secondary_navigation_quick_filters_and_sorting():
    with TestClient(app) as client:
        _login(client)
        response = client.get("/app/employees")
        assert response.status_code == 200
        for expected in (
            'aria-label="Subsecciones de mantenimiento"',
            'aria-current="page">Funcionarios',
            'data-employee-filter="active"',
            'data-employee-filter="ips"',
            'data-employee-filter="no-section"',
            'id="employeeSort"',
            'id="employeeTable"',
            'id="employeeClientEmpty"',
        ):
            assert expected in response.text


def test_maintenance_assets_and_detail_tabs_are_loaded_and_scoped():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "maintenance-workspace-263.css").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "maintenance-workspace-263.js").read_text(encoding="utf-8")
    company = (ROOT / "app" / "templates" / "company_detail.html").read_text(encoding="utf-8")
    employee = (ROOT / "app" / "templates" / "employee_detail.html").read_text(encoding="utf-8")

    assert "maintenance-workspace-263.css" in base
    assert "maintenance-workspace-263.js" in base
    assert "data-company-directory" in js and "data-employee-row" in js
    assert "field-validation-message" in js and "aria-invalid" in js
    assert "prefers-reduced-motion:reduce" in css
    assert 'id="company-employees"' in company and 'id="company-branches"' in company
    assert "Subsecciones del expediente de empresa" in company
    assert 'id="employee-overview"' in employee and 'id="timeline"' in employee
    assert "Subsecciones del expediente del funcionario" in employee
