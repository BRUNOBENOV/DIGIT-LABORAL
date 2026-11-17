from __future__ import annotations

import re
from datetime import date, datetime
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader
from sqlalchemy import select

from app.config import settings
from app.main import app
from app.database import SessionLocal
from app.models import CalculationRecord, Company, Employee
from app.report_center import REPORTS, fetch_report, get_report, make_pdf, make_xlsx, report_columns


def _login(client: TestClient) -> None:
    page = client.get("/login")
    token_match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert page.status_code == 200 and token_match
    response = client.post(
        "/login",
        data={
            "email": "admin@digitlaboral.com.py",
            "password": settings.demo_admin_password,
            "csrf_token": token_match.group(1),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_reports_catalog_lists_every_requested_submodule():
    assert len(REPORTS) == 35
    assert len(set(REPORTS)) == len(REPORTS)
    with TestClient(app) as client:
        _login(client)
        catalog = client.get("/api/reports/catalog")
        assert catalog.status_code == 200
        payload = catalog.json()
        keys = [report["key"] for group in payload["groups"] for report in group["reports"]]
        assert payload["total"] == 35
        assert len(keys) == 35
        assert set(keys) == set(REPORTS)
        page = client.get("/app/reports")
        assert page.status_code == 200
        assert "Informes laborales" in page.text
        assert "Listado Examen Médico" in page.text
        assert "Liquidación de Salarios" in page.text
        assert page.text.count("Liquidación de Salarios") == 1
        assert "INFORME DEDICADO" not in page.text
        assert 'href="/app/reports/liquidacion-salario"' in page.text
        assert 'href="/app/reports/liquidaciones-salarios"' not in page.text


def test_all_report_data_endpoints_return_paginated_schema():
    with TestClient(app) as client:
        _login(client)
        for key, spec in REPORTS.items():
            response = client.get(f"/api/reports/{key}?page=1&page_size=10")
            assert response.status_code == 200, f"{key}: {response.text[:300]}"
            payload = response.json()
            assert payload["report"]["key"] == key
            assert payload["report"]["label"] == spec.label
            assert isinstance(payload["records"], list)
            assert isinstance(payload["columns"], list) and payload["columns"]
            assert payload["page"] == 1
            assert payload["page_size"] == 10
            assert payload["total"] >= 0
            assert payload["pages"] >= 0
        invalid = client.get("/api/reports/no-existe")
        assert invalid.status_code == 404


def test_report_detail_and_excel_pdf_exports_work():
    with TestClient(app) as client:
        _login(client)
        detail = client.get("/app/reports/listado-empresa")
        assert detail.status_code == 200
        assert "Listado Empresa" in detail.text
        assert "Aplicar" in detail.text

        excel = client.get("/api/reports/listado-empresa/export?format=xlsx")
        assert excel.status_code == 200
        assert excel.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert excel.content.startswith(b"PK")

        pdf = client.get("/app/reports/listado-empresa/export?format=pdf")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"].startswith("application/pdf")
        assert pdf.content.startswith(b"%PDF")

        bad_format = client.get("/api/reports/listado-empresa/export?format=exe")
        assert bad_format.status_code == 400


def test_report_queries_include_professional_suite_calculations():
    marker = "report-center-suite-data-check"
    with TestClient(app) as client:
        _login(client)
        with SessionLocal() as db:
            company = db.scalar(select(Company).order_by(Company.id))
            assert company is not None
            company_id = company.id
            for calc_type in ("suite_salary", "suite_settlement", "suite_aguinaldo", "suite_vacation"):
                db.add(
                    CalculationRecord(
                        company_id=company_id,
                        calculation_type=calc_type,
                        reference_period="2026-10",
                        amount=987654,
                        status="Borrador",
                        source="test",
                        notes=marker,
                        created_by="qa-report-center",
                    )
                )
            db.commit()

        cases = (
            ("liquidacion-salario", "suite_salary"),
            ("liquidacion-haberes", "suite_settlement"),
            ("liquidacion-aguinaldo", "suite_aguinaldo"),
            ("liquidacion-vacacion", "suite_vacation"),
        )
        expected_labels = {
            "suite_salary": "Salario neto",
            "suite_settlement": "Liquidación de haberes",
            "suite_aguinaldo": "Aguinaldo",
            "suite_vacation": "Vacaciones",
        }
        for report_key, expected_type in cases:
            response = client.get(
                f"/api/reports/{report_key}",
                params={"company_id": company_id, "q": marker, "page_size": 100},
            )
            assert response.status_code == 200, f"{report_key}: {response.text[:250]}"
            payload = response.json()
            assert any(
                row.get("Importe (Gs.)") == 987654
                and row.get("Tipo de cálculo") == expected_labels[expected_type]
                for row in payload["records"]
            ), report_key


def test_excel_export_forces_user_supplied_strings_to_text():
    spec = get_report("listado-empresa")
    assert spec is not None
    row = {column: "" for column in report_columns(spec)}
    row["Empresa"] = '=HYPERLINK("https://example.invalid","click")'
    row["Nombre comercial"] = '\t=HYPERLINK("https://example.invalid","click")'
    payload = make_xlsx(spec, [row])
    workbook = load_workbook(BytesIO(payload), data_only=False)
    cell = workbook["Informe"].cell(row=3, column=2)
    tab_prefixed = workbook["Informe"].cell(row=3, column=3)
    assert cell.data_type != "f"
    assert isinstance(cell.value, str) and cell.value.startswith("'=")
    assert tab_prefixed.data_type != "f"
    assert isinstance(tab_prefixed.value, str) and tab_prefixed.value.startswith("'\t=")


def test_report_year_filters_use_termination_and_active_annual_coverage():
    """A former worker hired before the requested year must not disappear."""
    marker = "audit-report-years-" + uuid4().hex[:12]
    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        worker = Employee(
            company_id=company.id, full_name=marker, document_number=marker,
            admission_date=date(2020, 5, 12), termination_date=date(2026, 10, 3),
            status="Desvinculado", base_salary=3044000,
        )
        db.add(worker)
        db.flush()
        options = dict(company_ids=[company.id], company_id=company.id, q=marker)
        def records(report_key, year):
            return fetch_report(db, REPORTS[report_key], **options, year=year)["records"]

        assert len(records("personales-despedidos", 2026)) == 1
        assert records("personales-despedidos", 2020) == []
        assert len(records("listado-anual-reg-empleados-obreros", 2025)) == 1
        assert len(records("p-empleados-obreros", 2026)) == 1
        assert records("p-empleados-obreros", 2027) == []
        assert len(records("listado-empl-fecha", 2020)) == 1
        assert records("listado-empl-fecha", 2026) == []
        db.rollback()


def test_calculation_reports_filter_by_reference_period_not_save_timestamp():
    marker = "audit-report-period-" + uuid4().hex[:12]
    with SessionLocal() as db:
        company = db.scalar(select(Company).order_by(Company.id))
        assert company is not None
        for period, registered in (
            ("2025-08", datetime(2026, 11, 2)),
            ("2026-10", datetime(2025, 11, 2)),
        ):
            db.add(CalculationRecord(
                company_id=company.id, calculation_type="suite_settlement",
                reference_period=period, amount=12345, status="Borrador",
                source="audit", notes=marker, created_at=registered,
                created_by="audit-test",
            ))
        db.flush()
        options = dict(company_ids=[company.id], company_id=company.id, q=marker)
        def count(*, year=None, period=None):
            return len(fetch_report(
                db, REPORTS["liquidacion-haberes"], **options, year=year, period=period,
            )["records"])

        assert count(year=2025) == 1
        assert count(year=2026) == 1
        assert count(period="2025-08") == 1
        assert count(period="2026-10") == 1
        assert count(year=2025, period="2025-08") == 1
        assert count(year=2026, period="2025-08") == 0
        db.rollback()


def test_wide_salary_report_pdf_uses_large_landscape_paper():
    spec = REPORTS["planilla-de-pago"]
    row = {column: "" for column in report_columns(spec)}
    row["Funcionario"] = "Funcionario de prueba"
    payload = make_pdf(spec, [row])
    document = PdfReader(BytesIO(payload))
    assert len(document.pages) == 1
    assert float(document.pages[0].mediabox.width) > 1000  # landscape A3
    assert float(document.pages[0].mediabox.width) > float(document.pages[0].mediabox.height)


def test_report_filter_form_does_not_offer_ignored_fields():
    with TestClient(app) as client:
        _login(client)
        companies = client.get("/app/reports/listado-empresa")
        assert companies.status_code == 200
        assert 'name="year"' not in companies.text
        assert 'name="period"' not in companies.text
        assert 'name="employee_id"' not in companies.text

        dismissed = client.get("/app/reports/personales-despedidos")
        assert dismissed.status_code == 200
        assert "Año de egreso" in dismissed.text
        assert 'name="period"' not in dismissed.text

        settlements = client.get("/app/reports/liquidacion-haberes")
        assert settlements.status_code == 200
        assert "Año del período" in settlements.text
        assert 'name="period"' in settlements.text

        for yearly in ("planilla-de-aguinaldo", "listado-vacacion"):
            response = client.get(f"/app/reports/{yearly}")
            assert response.status_code == 200
            assert 'name="year"' in response.text
            assert 'name="period"' not in response.text
