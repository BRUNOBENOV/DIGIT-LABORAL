from __future__ import annotations

import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Employee


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


def test_seeded_employee_can_be_loaded_by_company_and_legajo():
    with SessionLocal() as db:
        employee = db.scalar(
            select(Employee)
            .where(Employee.employee_code.is_not(None))
            .order_by(Employee.id)
        )
        assert employee is not None
        employee_id = employee.id
        employee_code = employee.employee_code
        company_id = employee.company_id

    with TestClient(app) as client:
        _login(client)
        response = client.get(
            f"/api/employees/by-code/{employee_code}?company_id={company_id}"
        )
        assert response.status_code == 200, response.text
        record = response.json()
        assert record["id"] == employee_id
        assert record["employee_code"] == employee_code
        assert record["company_id"] == company_id
        assert record["full_name"]
        assert "daily_hours" in record
        assert "ips_number" in record
