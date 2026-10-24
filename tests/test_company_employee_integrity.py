from __future__ import annotations

import re
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.import_service import normalize_document_number, parse_employee_import, parse_money
from app.main import app
from app.models import Company, Employee


def _login(client: TestClient) -> str:
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
    dashboard = client.get("/app")
    dashboard_token = re.search(r'name="csrf_token" value="([^"]+)"', dashboard.text)
    assert dashboard.status_code == 200 and dashboard_token
    return dashboard_token.group(1)


def _dot_format_document(value: str) -> str:
    groups = []
    while value:
        groups.append(value[-3:])
        value = value[:-3]
    return ".".join(reversed(groups))


def test_employee_import_normalizes_document_numbers_and_marks_in_file_duplicates():
    csv_content = (
        "nombre_completo,cedula,cargo,fecha_ingreso,salario_base,aporta_ips\n"
        "Ana Pérez,1.234.567,Auxiliar,2024-02-01,3044000,Sí\n"
        "Ana duplicada,1234567,Auxiliar,2024-02-01,3044000,No\n"
    ).encode("utf-8")

    rows = parse_employee_import(csv_content, "funcionarios.csv")

    assert len(rows) == 2
    assert rows[0].valid
    assert rows[0].data["document_number"] == "1234567"
    assert not rows[1].valid
    assert any("fila 2" in error for error in rows[1].errors)


def test_employee_import_rejects_duplicate_headers_after_normalization():
    csv_content = (
        "nombre_completo,cedula,Cédula,cargo,fecha_ingreso,salario_base\n"
        "Ana Pérez,1234567,1234567,Auxiliar,2024-02-01,3044000\n"
    ).encode("utf-8")

    with pytest.raises(ValueError, match="columnas repetidas"):
        parse_employee_import(csv_content, "funcionarios.csv")


def test_employee_import_does_not_turn_invalid_money_or_ips_values_into_silent_data():
    csv_content = (
        "nombre_completo,cedula,cargo,fecha_ingreso,salario_base,aporta_ips\n"
        "Ana Pérez,1111111,Auxiliar,2024-02-01,-100,desconocido\n"
        "Bea Gómez,2222222,Auxiliar,2024-02-01,3.044.000,No\n"
    ).encode("utf-8")

    rows = parse_employee_import(csv_content, "funcionarios.csv")

    assert not rows[0].valid
    assert any("salario base no es válido" in error for error in rows[0].errors)
    assert rows[0].data["ips_contributor"] is True
    assert any("aporta_ips" in warning for warning in rows[0].warnings)
    assert rows[1].valid
    assert rows[1].data["base_salary"] == 3_044_000
    assert rows[1].data["ips_contributor"] is False
    assert parse_money("Gs. 3.044.000") == 3_044_000
    assert parse_money(-100) is None
    assert parse_money(3_044_000.5) is None
    assert parse_money("3.044.000,50") is None
    assert normalize_document_number(" 1.234.567 ") == "1234567"


def test_employee_form_shows_only_a_company_specific_branch_selector():
    with TestClient(app) as client:
        _login(client)
        response = client.get("/app/employees")
        assert response.status_code == 200
        assert 'id="employeeCompany"' in response.text
        assert 'id="employeeBranch"' in response.text
        assert 'data-company="' in response.text


def test_employee_create_accepts_blank_optional_birth_date_and_normalizes_duplicate_document():
    with TestClient(app) as client:
        csrf = _login(client)
        with SessionLocal() as db:
            employee = next(
                (
                    item for item in db.scalars(select(Employee).order_by(Employee.id))
                    if item.document_number.isdigit() and len(item.document_number) >= 4
                ),
                None,
            )
            assert employee is not None
            company_id = employee.company_id
            dotted_document = _dot_format_document(employee.document_number)

        response = client.post(
            "/app/employees",
            data={
                "csrf_token": csrf,
                "company_id": str(company_id),
                "full_name": "Registro duplicado de prueba",
                "document_number": dotted_document,
                "position": "Auxiliar de prueba",
                "admission_date": "2024-02-01",
                "birth_date": "",
                "branch_id": "",
                "base_salary": "3044000",
                "contract_type": "Tiempo indefinido",
                "payment_frequency": "Mensual",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/app/employees?duplicate=1"


def test_employee_create_rejects_an_unrelated_branch_before_writing_the_employee():
    unique_document = f"QA-{uuid.uuid4().hex[:14]}"
    with TestClient(app) as client:
        csrf = _login(client)
        with SessionLocal() as db:
            company = db.scalar(select(Company).order_by(Company.id))
            assert company is not None
            company_id = company.id

        response = client.post(
            "/app/employees",
            data={
                "csrf_token": csrf,
                "company_id": str(company_id),
                "full_name": "Funcionario de prueba",
                "document_number": unique_document,
                "position": "Auxiliar de prueba",
                "admission_date": "2024-02-01",
                "birth_date": "",
                "branch_id": "999999999",
                "base_salary": "3044000",
                "contract_type": "Tiempo indefinido",
                "payment_frequency": "Mensual",
            },
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert "sucursal seleccionada" in response.text.lower()
        with SessionLocal() as db:
            assert db.scalar(
                select(Employee).where(
                    Employee.company_id == company_id,
                    Employee.document_number == unique_document,
                )
            ) is None


def test_company_create_rejects_blank_legal_name_and_ruc_server_side():
    with TestClient(app) as client:
        csrf = _login(client)
        missing_name = client.post(
            "/app/companies",
            data={"csrf_token": csrf, "legal_name": "   ", "ruc": f"QA-{uuid.uuid4().hex[:12]}"},
            follow_redirects=False,
        )
        assert missing_name.status_code == 303
        assert "form_error=" in missing_name.headers["location"]
        assert "open=companyModal" in missing_name.headers["location"]

        missing_ruc = client.post(
            "/app/companies",
            data={"csrf_token": csrf, "legal_name": f"Empresa de prueba {uuid.uuid4().hex[:8]}", "ruc": "  "},
            follow_redirects=False,
        )
        assert missing_ruc.status_code == 303
        assert "form_error=" in missing_ruc.headers["location"]
