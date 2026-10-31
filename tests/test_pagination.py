from __future__ import annotations

from datetime import date
import re
from urllib.parse import parse_qs, urlsplit
import uuid

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import (
    CalculationRecord, Company, CompanyBranding, CompanyComplianceProfile, CompanySection,
    Employee, Payroll, PayrollLine, Studio, User,
)
from app.pagination import Pagination


def _soup(response):
    assert response.status_code == 200, response.text[:500]
    return BeautifulSoup(response.text, "html.parser")


def _pager(response):
    soup = _soup(response)
    pager = soup.select_one("[data-pagination]")
    assert pager is not None
    assert [int(option["value"]) for option in pager.select("[data-page-size-form] option")] == [25, 50, 100, 200]
    return soup, pager


@pytest.fixture(scope="module")
def directory():
    """Synthetic tenant-scoped data with a real page 80; never touches production."""
    marker = "Pagination-" + uuid.uuid4().hex[:12]
    with TestClient(app) as client:
        token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/login").text).group(1)
        assert client.post("/login", data={"email": "admin@digitlaboral.com.py", "password": settings.demo_admin_password, "csrf_token": token}, follow_redirects=False).status_code == 303
        with SessionLocal() as db:
            studio_id = db.scalar(select(User.studio_id).where(User.email == "admin@digitlaboral.com.py"))
            base_code = (db.scalar(select(func.max(Company.company_code)).where(Company.studio_id == studio_id)) or 0) + 100
            companies = [Company(studio_id=studio_id, company_code=base_code+i, legal_name=f"{marker} Company {i:03}", ruc=f"{marker}-{i}", city="Ciudad del Este", status="Archivada" if i == 119 else "Activa") for i in range(120)]
            db.add_all(companies)
            db.flush()
            company_id = companies[0].id
            section = CompanySection(company_id=company_id, name=marker, section_code=1)
            db.add(section)
            db.add(CompanyBranding(company_id=company_id, logo_bytes=b"synthetic-logo"))
            db.add(CompanyComplianceProfile(company_id=company_id, department="Alto Paraná"))
            db.flush()
            employees = [Employee(company_id=company_id, employee_code=i+1, full_name=f"{marker} Employee {i:04}", document_number=f"{marker}-{i}", admission_date=date(2020, 1, 1), section_id=section.id if i % 2 else None, ips_contributor=i % 3 == 0, status="Archivado" if i == 2004 else ("Activo" if i % 10 == 0 else "Desvinculado"), base_salary=3_000_000+i) for i in range(2005)]
            db.add_all(employees)
            db.flush()
            for i in range(120):
                payroll = Payroll(company_id=company_id, period=f"{2000+i//12}-{i%12+1:02}", status="Cerrada" if i % 2 else "Borrador", total_gross=100_000+i, total_net=90_000+i, notes=f"{marker} payroll {i:03}")
                payroll.lines = [PayrollLine(employee_id=employees[i].id)]
                db.add(payroll)
            db.add_all([CalculationRecord(company_id=company_id, employee_id=employees[0].id, calculation_type="suite_salary", amount=100_000+i, status="Aprobado", reference_period="2026-10", notes=f"{marker} salary {i:03}") for i in range(205)])
            other_studio = Studio(name=marker+" Foreign")
            db.add(other_studio)
            db.flush()
            foreign = Company(studio_id=other_studio.id, company_code=1, legal_name=marker+" Foreign", ruc=marker+" Foreign")
            db.add(foreign)
            db.flush()
            foreign_id = foreign.id
            company_ids = [company.id for company in companies] + [foreign.id]
            other_studio_id = other_studio.id
            db.commit()
        try:
            yield client, marker, company_id, foreign_id
        finally:
            with SessionLocal() as db:
                for company in db.scalars(select(Company).where(Company.id.in_(company_ids))).all():
                    db.delete(company)
                db.flush()
                db.delete(db.get(Studio, other_studio_id))
                db.commit()


def test_pagination_boundaries_ranges_window_and_safe_urls():
    empty = Pagination("/app/employees", 0, 80, 25)
    assert (empty.page, empty.pages, empty.start, empty.end) == (1, 1, 0, 0)
    last = Pagination("/app/employees", 2004, 999999, 25, {"q": "María & Hijos", "direction": "desc", "company_id": None})
    assert (last.page, last.pages, last.start, last.end) == (81, 81, 2001, 2004)
    assert last.numbers == [1, None, 79, 80, 81]
    assert Pagination("/list", 1000000, 80, 25).numbers == [1, None, 78, 79, 80, 81, 82, None, 40000]
    assert Pagination("/list", 100, -50, 999999).page_size == 100
    assert parse_qs(urlsplit(last.url(page=1)).query) == {"q": ["María & Hijos"], "direction": ["desc"], "page": ["1"], "page_size": ["25"]}


def test_employee_page_80_search_and_last_page_have_correct_ranges(directory):
    client, marker, company_id, _ = directory
    filters = {"company_id": company_id, "q": marker, "employee_sort": "code", "direction": "asc", "page_size": 25}
    soup, pager = _pager(client.get("/app/employees", params={**filters, "page": 80}))
    assert "Mostrando 1976 a 2000 de 2004 registros" in pager.get_text(" ", strip=True)
    assert [int(row["data-employee-code"]) for row in soup.select("tr[data-employee-row]")] == list(range(1976, 2001))
    assert pager.select_one(".app-pagination-ellipsis")
    last_link = pager.find("a", string="Última »")["href"]
    last_soup, last_pager = _pager(client.get(last_link))
    assert "Mostrando 2001 a 2004 de 2004 registros" in last_pager.get_text(" ", strip=True)
    assert [int(row["data-employee-code"]) for row in last_soup.select("tr[data-employee-row]")] == [2001, 2002, 2003, 2004]
    assert last_pager.find("button", string="Siguiente ›").has_attr("disabled")
    assert last_pager.find("button", string="Última »").has_attr("disabled")
    # Search runs before pagination even when an old bookmark still says page 80.
    search, search_pager = _pager(client.get("/app/employees", params={**filters, "page": 80, "q": marker+" Employee 2002"}))
    assert search_pager["data-page"] == "1"
    assert [int(row["data-employee-code"]) for row in search.select("tr[data-employee-row]")] == [2003]


@pytest.mark.parametrize("size", [25, 50, 100, 200])
def test_employee_page_sizes_keep_whole_dataset_sort_filters_and_urls(directory, size):
    client, marker, company_id, _ = directory
    soup, pager = _pager(client.get("/app/employees", params={"company_id": company_id, "q": marker, "employee_quick": "ips", "employee_sort": "code", "direction": "desc", "page_size": size, "show_archived": "true"}))
    codes = [int(row["data-employee-code"]) for row in soup.select("tr[data-employee-row]")]
    assert len(codes) == size
    assert codes == list(range(2005, 0, -3))[:size]
    assert pager["data-total"] == "669"
    next_url = pager.find("a", rel="next")["href"]
    params = parse_qs(urlsplit(next_url).query)
    assert params["page_size"] == [str(size)] and params["page"] == ["2"]
    assert params["employee_quick"] == ["ips"] and params["direction"] == ["desc"]
    assert params["show_archived"] == ["true"] and params["q"] == [marker]
    assert pager.find("button", string="« Primera").has_attr("disabled")
    assert pager.find("button", string="‹ Anterior").has_attr("disabled")


def test_quick_filters_search_all_employees_and_empty_results_keep_the_bar(directory):
    client, marker, company_id, _ = directory
    active, active_pager = _pager(client.get("/app/employees", params={"company_id": company_id, "employee_quick": "active", "page_size": 25, "employee_sort": "code", "direction": "desc"}))
    assert active_pager["data-total"] == "201"
    assert int(active.select_one("tr[data-employee-row]")["data-employee-code"]) == 2001
    _, no_section_pager = _pager(client.get("/app/employees", params={"company_id": company_id, "employee_quick": "no-section", "show_archived": "true"}))
    assert no_section_pager["data-total"] == "1003"
    _, empty = _pager(client.get("/app/employees", params={"company_id": company_id, "q": marker+" missing", "page": 80, "page_size": 25}))
    assert "Mostrando 0 a 0 de 0 registros" in empty.get_text(" ", strip=True)
    assert len(empty.select("nav button[disabled]")) == 4


def test_companies_paginate_search_filter_and_sort_before_sql_limit(directory):
    client, marker, company_id, foreign_id = directory
    soup, pager = _pager(client.get("/app/companies", params={"q": marker, "page_size": 25, "page": 2, "company_sort": "code", "direction": "desc"}))
    assert len(soup.select("[data-company-card]")) == 25
    assert pager["data-total"] == "120"  # The matching foreign tenant is excluded.
    codes = [int(card["data-company-code"]) for card in soup.select("[data-company-card]")]
    assert codes == sorted(codes, reverse=True)
    _, active = _pager(client.get("/app/companies", params={"q": marker, "company_quick": "active"}))
    assert active["data-total"] == "119"
    _, no_logo = _pager(client.get("/app/companies", params={"q": marker, "company_quick": "no-logo"}))
    assert no_logo["data-total"] == "119"
    sorted_soup, _ = _pager(client.get("/app/companies", params={"q": marker, "company_sort": "employees", "direction": "desc", "page_size": 25}))
    assert sorted_soup.select_one("[data-company-card]")["data-company-employees"] == "2005"
    _, search = _pager(client.get("/app/companies", params={"q": marker+" Company 119", "page": 80}))
    assert (search["data-page"], search["data-total"]) == ("1", "1")
    _, department = _pager(client.get("/app/companies", params={"q": marker, "department": "Alto Paraná", "city": "Ciudad del Este", "page_size": 25}))
    assert department["data-total"] == "1"
    assert client.get("/app/employees", params={"company_id": foreign_id}).status_code == 404


def test_payroll_and_salary_reports_use_shared_ranges_and_sort_globally(directory):
    client, marker, company_id, foreign_id = directory
    soup, pager = _pager(client.get("/app/payrolls", params={"company_id": company_id, "q": marker, "page_size": 25, "page": 2, "sort": "gross", "direction": "desc"}))
    assert pager["data-total"] == "120"
    assert "Mostrando 26 a 50 de 120 registros" in pager.get_text(" ", strip=True)
    values = [int(re.sub(r"\D", "", row.select("td")[3].get_text())) for row in soup.select("#payrollTable tbody tr")]
    assert values == list(range(100094, 100069, -1))
    _, closed = _pager(client.get("/app/payrolls", params={"company_id": company_id, "status": "Cerrada", "page_size": 25}))
    assert closed["data-total"] == "60"
    _, by_employee = _pager(client.get("/app/payrolls", params={"company_id": company_id, "q": marker+" Employee 0119", "page": 80}))
    assert (by_employee["data-page"], by_employee["data-total"]) == ("1", "1")
    assert client.get("/app/payrolls", params={"company_id": foreign_id}).status_code == 404
    salary, salary_pager = _pager(client.get("/app/reports/liquidaciones-salarios", params={"company_id": company_id, "q": marker, "page_size": 200, "sort": "amount", "direction": "desc"}))
    assert salary_pager["data-total"] == "205" and salary_pager["data-page-size"] == "200"
    assert len(salary.select("#salaryReportTable tbody tr")) == 200
    last, last_pager = _pager(client.get(salary_pager.find("a", string="Última »")["href"]))
    assert "Mostrando 201 a 205 de 205 registros" in last_pager.get_text(" ", strip=True)
    assert len(last.select("#salaryReportTable tbody tr")) == 5


def test_generic_reports_support_200_and_clamp_old_search_pages(directory):
    client, marker, company_id, _ = directory
    soup, pager = _pager(client.get("/app/reports/listado-empleado", params={"company_id": company_id, "q": marker, "page_size": 200, "sort": "-salary"}))
    assert pager["data-page-size"] == "200" and len(soup.select("#reportTable tbody tr")) == 200
    params = parse_qs(urlsplit(pager.find("a", rel="next")["href"]).query)
    assert params["sort"] == ["-salary"] and params["page_size"] == ["200"]
    response = client.get("/api/reports/listado-empleado", params={"company_id": company_id, "q": marker+" Employee 2002", "page": 80, "page_size": 200})
    assert response.status_code == 200
    assert response.json()["page"] == 1 and response.json()["total"] == 1
