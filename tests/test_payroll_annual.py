from calendar import monthrange
from datetime import UTC, date, datetime
import io
import json

from pypdf import PdfReader
import pytest
from sqlalchemy import select

from app import main as core
from app.models import CalculationRecord, EmployeeComplianceProfile, EmployeeExit, Payroll, PayrollComplianceDetail, PayrollLine
from app.payroll_annual import NO_HISTORY, propose_annual_remuneration
from tests.test_labor_suite import token, web_case
from tests.test_settlement_legal_cases import settlement_data


@pytest.fixture
def annual_case(web_case):
    client, db, box, company, employee, other = web_case
    employee.admission_date = date(2024, 1, 1)
    db.add(EmployeeComplianceProfile(employee_id=employee.id, salary_type="Jornal"))
    lines = []
    for period in ["2024-12", "2025-01", "2025-02", "2025-03", "2025-04"]:
        payroll = Payroll(company_id=company.id, period=period, status="Cerrada", closed_at=datetime(2025, 5, 1, tzinfo=UTC))
        db.add(payroll); db.flush()
        line = PayrollLine(payroll_id=payroll.id, employee_id=employee.id, base_salary=3_000_000,
                           overtime=100_000, commissions=200_000, bonuses=50_000, other_income=0,
                           absences_discount=50_000, ips_employee=270_000, ips_base=3_000_000, ips_rate=9,
                           advances=100_000, other_discount=20_000, gross=3_350_000,
                           total_discounts=440_000, net=2_910_000)
        db.add(line); db.flush()
        year, month = map(int, period.split("-"))
        db.add(PayrollComplianceDetail(payroll_line_id=line.id, period_start=date(year, month, 1),
            period_end=date(year, month, monthrange(year, month)[1]), night_surcharge=30_000,
            overtime_day=100_000, vacation_pay=100_000, family_allowance=152_200, employer_ips=552_750))
        lines.append(line)
    db.commit()
    yield client, db, box, company, employee, other, lines


def proposal(case, **changes):
    client, _db, _box, company, employee, *_ = case
    return client.get("/api/liquidaciones/remuneracion-anual", params={
        "company_id":company.id, "employee_id":employee.id, "end_date":"2025-03-31", **changes})


def selected(case):
    client, _db, _box, company, employee, *_ = case
    source = proposal(case).json()
    return settlement_data(company_id=str(company.id), employee_id=str(employee.id), reason="resignation",
        start_date=employee.admission_date.isoformat(), end_date="2025-03-31", annual_origin="payroll",
        annual_payroll_fingerprint=source["fingerprint"], annual_remuneration=str(source["annual_remuneration"]),
        csrf_token=token(client))


def test_calendar_year_sum_uses_earnings_not_net_and_does_not_duplicate_detail(annual_case):
    response = proposal(annual_case)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["is_available"] and data["is_complete"]
    assert data["window_start"] == "2025-01-01" and data["window_end"] == "2025-03-31"
    assert data["included_count"] == data["expected_count"] == 3
    assert data["annual_remuneration"] == 9_900_000 and data["aguinaldo_accrued"] == 825_000
    assert [row["period"] for row in data["periods"]] == ["2025-01", "2025-02", "2025-03"]
    assert data["periods"][0]["remuneration"] == 3_300_000
    assert len(data["fingerprint"]) == 64  # Jornal salary mode does not change actual annual earnings.


@pytest.mark.parametrize("change, expected", [
    ("open", "Nómina no cerrada"), ("no_close", "Falta constancia de cierre"),
    ("gross", "Importes inconsistentes"), ("ips", "Importes inconsistentes"),
    ("other", "Otros ingresos sin clasificación"), ("detail_other", "Otros ingresos sin clasificación"),
    ("partial", "El período no coincide"), ("incomplete_dates", "El período no coincide"),
])
def test_unusable_period_is_excluded_and_total_remains_explicitly_partial(annual_case, change, expected):
    _client, db, *_rest, lines = annual_case
    line = lines[2]
    detail = db.scalar(select(PayrollComplianceDetail).where(PayrollComplianceDetail.payroll_line_id == line.id))
    if change == "open": line.payroll.status = "Borrador"
    elif change == "no_close": line.payroll.closed_at = None
    elif change == "gross": line.gross += 1
    elif change == "ips": line.ips_employee += 1
    elif change == "other":
        line.other_income = 100_000; line.gross += 100_000; line.net += 100_000
    elif change == "detail_other": detail.other_income_detail = 100_000
    elif change == "partial": detail.period_end = date(2025, 2, 20)
    else: detail.period_end = None
    db.commit()
    data = proposal(annual_case).json()
    assert data["is_available"] and not data["is_complete"]
    assert data["annual_remuneration"] == 6_600_000 and data["aguinaldo_accrued"] == 550_000
    assert data["periods"][1]["status"].startswith(expected)
    assert data["periods"][1]["remuneration"] is None
    assert any("Cobertura parcial" in message for message in data["warnings"])


def test_real_payroll_lines_without_complementary_dates_are_usable_for_full_months(annual_case):
    _client, db, *_rest, lines = annual_case
    for line in lines:
        db.delete(db.scalar(select(PayrollComplianceDetail).where(PayrollComplianceDetail.payroll_line_id == line.id)))
    db.commit()
    assert proposal(annual_case).json()["is_complete"]


def test_payrolls_created_and_closed_through_application_are_automatically_computable(web_case):
    client, db, _box, company, employee, *_ = web_case
    employee.admission_date = date(2025,1,1); db.commit()
    csrf = token(client)
    for month in range(1,4):
        response = client.post("/app/payrolls", data=dict(csrf_token=csrf,company_id=company.id,period=f"2025-{month:02d}"), follow_redirects=False)
        assert response.status_code == 303, response.text
        payroll_id = int(response.headers["location"].split("/")[-1])
        closed = client.post(f"/app/payrolls/{payroll_id}/status", data=dict(csrf_token=csrf,status="Cerrada"),follow_redirects=False)
        assert closed.status_code == 303, closed.text
    data = proposal(web_case).json()
    assert data["is_complete"] and data["annual_remuneration"] == 10_500_000
    assert data["aguinaldo_accrued"] == 875_000


def test_partial_admission_and_exit_require_exact_documented_source_dates(annual_case):
    _client, db, _box, _company, employee, _other, lines = annual_case
    employee.admission_date = date(2025, 1, 10)
    first = db.scalar(select(PayrollComplianceDetail).where(PayrollComplianceDetail.payroll_line_id == lines[1].id))
    last = db.scalar(select(PayrollComplianceDetail).where(PayrollComplianceDetail.payroll_line_id == lines[3].id))
    first.period_start = employee.admission_date
    db.commit()
    data = proposal(annual_case, end_date="2025-03-15").json()
    assert data["annual_remuneration"] == 6_600_000 and not data["is_complete"]
    last.period_end = date(2025, 3, 15); db.commit()
    data = proposal(annual_case, end_date="2025-03-15").json()
    assert data["window_start"] == "2025-01-10" and data["is_complete"]
    assert data["annual_remuneration"] == 9_900_000


def test_missing_history_never_becomes_zero(web_case):
    client, db, _box, company, employee, *_ = web_case
    employee.admission_date = date(1999, 2, 11); db.commit()
    data = proposal(web_case).json()
    assert not data["is_available"] and data["annual_remuneration"] is None and data["aguinaldo_accrued"] is None
    assert NO_HISTORY in data["warnings"]
    response = client.post("/app/liquidaciones/calcular", data=settlement_data(
        company_id=str(company.id), employee_id=str(employee.id), annual_remuneration="19037824", csrf_token=token(client)), headers={"Accept":"application/json"})
    assert response.status_code == 200 and response.json()["values"]["aguinaldo"] == 1_586_485


def test_future_or_mismatched_legajo_dates_do_not_auto_apply(annual_case):
    _client, db, _box, _company, employee, *_ = annual_case
    data = propose_annual_remuneration(db, employee, date(2025, 3, 31), today=date(2025, 3, 1))
    assert not data["is_available"] and data["annual_remuneration"] is None
    data = proposal(annual_case, start_date="2024-01-02").json()
    assert not data["is_available"]
    employee.termination_date = date(2025, 3, 30); db.commit()
    assert not proposal(annual_case).json()["is_available"]


def test_private_page_prefills_and_locks_from_closed_payrolls(annual_case):
    client, db, _box, company, employee, *_ = annual_case
    record = EmployeeExit(company_id=company.id, employee_id=employee.id, effective_date=date(2025,3,31),
                          reason="resignation", initiated_by="Trabajador", status="Programado")
    db.add(record); db.commit()
    response = client.get("/app/liquidaciones", params=dict(tipo="settlement",company_id=company.id,employee_id=employee.id,exit_id=record.id))
    assert response.status_code == 200
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(response.text, "html.parser")
    annual = soup.select_one('[name="annual_remuneration"]')
    assert annual["value"] == "9900000" and annual.has_attr("readonly")
    assert soup.select_one('[name="annual_origin"]')["value"] == "payroll"
    assert soup.select_one('[data-annual-manual]') is not None


def test_server_rechecks_amount_and_fingerprint_on_calculate_save_and_export(annual_case):
    client, db, _box, _company, _employee, _other, lines = annual_case
    data = selected(annual_case)
    bad = dict(data, annual_remuneration="9900001")
    assert client.post("/app/liquidaciones/calcular", data=bad, headers={"Accept":"application/json"}).status_code == 422
    lines[1].advances += 1; lines[1].total_discounts += 1; lines[1].net -= 1; db.commit()
    for path in ["/app/liquidaciones/calcular", "/app/liquidaciones/guardar", "/app/liquidaciones/exportar/pdf"]:
        response = client.post(path, data=data, headers={"Accept":"application/json"}, follow_redirects=False)
        assert response.status_code == 422, (path,response.status_code)
    assert not db.scalar(select(CalculationRecord.id))


def test_saved_provenance_reprints_and_approval_rechecks_sources(annual_case):
    client, db, _box, _company, _employee, _other, lines = annual_case
    data = selected(annual_case)
    response = client.post("/api/calculations", json=data, headers={"X-CSRF-Token":data["csrf_token"]})
    assert response.status_code == 201, response.text
    item = db.get(CalculationRecord, response.json()["id"])
    result = json.loads(item.result_json)
    assert result["annual_provenance"]["annual_remuneration"] == 9_900_000
    core._revalidate_calculation_before_approval(item, db)
    pdf = client.get(f"/app/liquidaciones/{item.id}/exportar/pdf")
    assert pdf.status_code == 200, pdf.text[:200]
    original_text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Cobertura anual" in original_text
    lines[1].payroll.status = "Borrador"; db.commit()
    assert client.patch(f"/api/calculations/{item.id}", json={"status":"Aprobado"}, headers={"X-CSRF-Token":data["csrf_token"]}).status_code == 409
    reprint = client.get(f"/app/liquidaciones/{item.id}/exportar/pdf")
    assert "".join(page.extract_text() for page in PdfReader(io.BytesIO(reprint.content)).pages) == original_text
    db.refresh(item)
    assert json.loads(item.result_json) == result


def test_partial_annual_sources_cannot_be_approved_through_api(annual_case):
    client, db, _box, _company, _employee, _other, lines = annual_case
    lines[1].payroll.status = "Borrador"; db.commit()
    data = selected(annual_case)
    response = client.post("/api/calculations", json=data, headers={"X-CSRF-Token":data["csrf_token"]})
    assert response.status_code == 201, response.text
    record_id = response.json()["id"]
    result = json.loads(db.get(CalculationRecord, record_id).result_json)
    assert result["partial"] and any("Cobertura parcial" in message for message in result["warnings"])
    assert client.patch(f"/api/calculations/{record_id}", json={"status":"Aprobado"}, headers={"X-CSRF-Token":data["csrf_token"]}).status_code == 409


def test_manual_unlock_removes_payroll_source_dependency(annual_case):
    client, db, _box, _company, _employee, _other, lines = annual_case
    data = dict(selected(annual_case), annual_origin="manual", annual_remuneration="19037824")
    lines[1].payroll.status = "Borrador"; db.commit()
    response = client.post("/api/calculations", json=data, headers={"X-CSRF-Token":data["csrf_token"]})
    assert response.status_code == 201, response.text
    item = db.get(CalculationRecord, response.json()["id"])
    assert "annual_payroll_fingerprint" not in json.loads(item.input_json)
    assert "annual_provenance" not in json.loads(item.result_json)


def test_source_endpoint_enforces_company_employee_scope_and_dates(annual_case):
    _client, _db, _box, _company, _employee, other, *_ = annual_case
    assert proposal(annual_case, employee_id=other.id).status_code == 404
    assert proposal(annual_case, company_id=other.company_id, employee_id=other.id).status_code == 404
    assert proposal(annual_case, end_date="2025-02-30").status_code == 422


@pytest.mark.parametrize("value, expected", [("19037824",1_586_485),("6",1),("0",0),("-1",None),("NaN",None),("1.5",None)])
def test_manual_accrual_preview_uses_engine_rounding_and_validation(web_case, value, expected):
    client, *_ = web_case
    payload = dict(kind="settlement", annual_remuneration=value, csrf_token=token(client))
    response = client.post("/herramientas/aguinaldo/previsualizar", data=payload)
    assert response.status_code == (200 if expected is not None else 422)
    if expected is not None: assert response.json()["aguinaldo_accrued"] == expected
    payload.pop("csrf_token")
    assert client.post("/herramientas/aguinaldo/previsualizar", data=payload).status_code == 403
