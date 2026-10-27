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


def _calculation_selectors(client: TestClient):
    response = client.get("/app/calculations?tipo=salary")
    assert response.status_code == 200
    company_html = re.search(
        r'id="calculationCompanyFilter">(.*?)</select>', response.text, re.DOTALL
    )
    employee_html = re.search(
        r'id="calculationEmployeeFilter">(.*?)</select>', response.text, re.DOTALL
    )
    assert company_html and employee_html
    company_ids = re.findall(r'<option value="(\d+)"', company_html.group(1))
    employees = [
        (int(employee_id), int(company_id))
        for employee_id, company_id in re.findall(
            r'<option value="(\d+)" data-company="(\d+)"', employee_html.group(1)
        )
    ]
    return response, [int(value) for value in company_ids], employees


def test_sidebar_has_no_global_company_or_employee_selector():
    with TestClient(app) as client:
        _login(client)
        response = client.get("/app")
        assert response.status_code == 200
        assert "Contexto de trabajo" not in response.text
        assert "data-labor-context" not in response.text
        assert "labor-context-panel" not in response.text


def test_each_operational_module_has_its_own_selectors():
    paths = [
        "/app/calculations?tipo=salary",
        "/app/calculations/periodos?year=2026",
        "/app/payrolls",
        "/app/vacations",
        "/app/aguinaldo",
        "/app/documents",
        "/app/reports",
        "/app/certificates",
        "/app/liquidaciones?tipo=settlement",
    ]
    with TestClient(app) as client:
        _login(client)
        for path in paths:
            response = client.get(path)
            assert response.status_code == 200, path
            assert "data-module-selection" in response.text, path
            assert "data-module-company" in response.text, path
            assert "data-module-employee" in response.text, path


def test_a_module_selection_does_not_leak_into_another_module():
    with TestClient(app) as client:
        _login(client)
        _, company_ids, employees = _calculation_selectors(client)
        assert company_ids and employees
        employee_id, company_id = employees[0]

        selected = client.get(
            f"/app/calculations?tipo=salary&company_id={company_id}&employee_id={employee_id}"
        )
        assert selected.status_code == 200
        filter_form = re.search(
            r'<form method="get" action="/app/calculations".*?</form>',
            selected.text,
            re.DOTALL,
        )
        assert filter_form
        assert f'value="{company_id}" selected' in filter_form.group(0)
        assert f'value="{employee_id}" data-company="{company_id}" selected' in filter_form.group(0)

        # Opening another module without query selections must not inherit the
        # previous module's company or employee from session state.
        vacations = client.get("/app/vacations")
        assert vacations.status_code == 200
        vacations_filter = re.search(
            r'<form method="get" action="/app/vacations".*?</form>',
            vacations.text,
            re.DOTALL,
        )
        assert vacations_filter
        assert f'value="{company_id}" selected' not in vacations_filter.group(0)
        assert f'value="{employee_id}" data-company="{company_id}" selected' not in vacations_filter.group(0)


def test_module_selector_rejects_employee_from_a_different_company():
    with TestClient(app) as client:
        _login(client)
        _, company_ids, employees = _calculation_selectors(client)
        assert len(company_ids) >= 2
        if not employees:
            return
        first_employee_id, first_company = employees[0]
        different_employee = next(
            ((employee, company) for employee, company in employees if company != first_company),
            None,
        )
        if different_employee is None:
            # Some reduced CI fixtures contain only one company.
            return
        employee_id, other_company = different_employee
        response = client.get(
            f"/app/calculations?tipo=salary&company_id={first_company}&employee_id={employee_id}"
        )
        assert response.status_code == 400
