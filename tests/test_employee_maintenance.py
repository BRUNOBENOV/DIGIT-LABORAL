from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


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


def test_employee_maintenance_ui_contains_legajo_lookup_and_section_filters():
    with TestClient(app) as client:
        _login(client)
        response = client.get("/app/employees")
        assert response.status_code == 200
        for expected in (
            'name="employee_code"',
            'id="employeeCode"',
            'name="section_id"',
            'name="status_filter"',
            'name="daily_hours"',
            'name="ips_number"',
            "Administrar secciones",
            "/api/employees/by-code/",
            "employeeCodeFeedback",
        ):
            assert expected in response.text
