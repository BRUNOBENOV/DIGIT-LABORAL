"""Regresión del cálculo salarial único: mensualizado y jornalero."""
import pytest

from app.labor_calculator import CalculationError, calculate
from tests.test_labor_suite import salary, web_case


def test_salary_monthly_keeps_divisor_30():
    result = calculate(salary(salary="3044000", days_paid="30", pay_basis="monthly"))
    assert result["gross"] == 3_044_000
    assert result["net"] == 2_770_040
    assert {"label": "Modalidad salarial", "value": "Mensualizado · divisor 30"} in result["facts"]


def test_salary_daily_reproduces_journal_reference_without_importing_mensual_divisor():
    result = calculate(salary(salary="3044000", days_paid="30", pay_basis="daily"))
    assert result["gross"] == 3_512_308
    assert result["net"] == 3_196_200
    assert {"label": "Modalidad salarial", "value": "Jornalero · divisor 26"} in result["facts"]
    assert any("más de 26" in warning for warning in result["warnings"])


def test_salary_daily_pact_rate_and_overtime_share_daily_base():
    result = calculate(salary(
        salary="3044000", days_paid="10", pay_basis="daily",
        daily_rate="120000", day_extra_hours="2"
    ))
    assert result["gross"] == 1_245_000
    assert result["net"] == 1_132_950
    assert any(item["label"] == "Horas extraordinarias diurnas (mínimo 50 %)"
               and item["amount"] == 45_000 for item in result["earnings"])


@pytest.mark.parametrize("data,field", [
    ({"pay_basis": "unknown"}, "pay_basis"),
    ({"pay_basis": "monthly", "days_paid": "31"}, "days_paid"),
    ({"pay_basis": "daily", "days_paid": "32"}, "days_paid"),
    ({"pay_basis": "daily", "daily_rate": "-1"}, "daily_rate"),
    ({"pay_basis": "daily", "daily_rate": "0"}, "daily_rate"),
])
def test_salary_rejects_invalid_modality_or_days(data, field):
    with pytest.raises(CalculationError) as exc:
        calculate(salary(**data))
    assert exc.value.field == field


def test_salary_legacy_entry_redirects_to_one_professional_calculator(web_case):
    client, *_ = web_case
    response = client.get("/app/calculations?tipo=salary", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/app/liquidaciones?tipo=salary")


def test_professional_jornal_exports_as_salary_not_unmapped_income():
    from app.approved_salary_import import _professional_line
    inputs = salary(salary="3044000", days_paid="26", pay_basis="daily")
    result = calculate(inputs)
    errors = []
    line, complements = _professional_line(None, inputs, result, errors)
    assert errors == []
    assert line.base_salary == 3_044_000
    assert line.gross == result["gross"]
    assert line.ips_base == 3_044_000


def test_salary_without_ips_is_explicitly_flagged_for_review():
    result = calculate(salary(salary="3044000", days_paid="30", apply_ips=""))
    assert result["gross"] == 3_044_000
    assert result["net"] == 3_044_000
    assert any("No se aplicó descuento IPS" in warning for warning in result["warnings"])


def test_month_parameter_populates_selected_salary_month_not_prior_period(web_case):
    from bs4 import BeautifulSoup
    client, _db, _box, company, employee, *_ = web_case
    page = client.get("/app/liquidaciones", params={
        "tipo":"salary", "month":"2026-11",
        "company_id":company.id, "employee_id":employee.id,
    })
    assert page.status_code == 200
    form = BeautifulSoup(page.text, "html.parser").select_one("#labor-form")
    assert form.select_one('[name="month"]')["value"] == "2026-11"
    assert 'name="month" value="2026-11"' in page.text
    assert "IPS desactivado por la ficha" not in page.text


def test_salary_month_controls_and_url_are_kept_in_sync():
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "app/static/salary-attendance.js").read_text(encoding="utf-8")
    assert "syncBrowserPeriod" in script
    assert "url.searchParams.set('month', month.value)" in script
    assert "suggestFullMonthDates()" in script
    assert "if (!proposal.available) suggestFullMonthDates();" in script
    assert "url.searchParams.delete('calculation_id')" in script


def test_employee_marked_noncontributor_is_disclosed_on_salary_form(web_case):
    client, db, _box, company, employee, *_ = web_case
    employee.ips_contributor = False
    db.commit()
    page = client.get("/app/liquidaciones", params={
        "tipo": "salary", "company_id": company.id, "employee_id": employee.id,
        "month": "2026-11",
    })
    assert page.status_code == 200
    assert "IPS desactivado por la ficha" in page.text
    assert '<div class="dl-alert" role="note">' not in page.text
    assert 'data-quick-step="4"' in page.text


def test_salary_form_relegates_optional_reviews_inside_base_step(web_case):
    from bs4 import BeautifulSoup
    client, db, _box, company, employee, *_ = web_case
    page = client.get("/app/liquidaciones", params={
        "tipo": "salary", "company_id": company.id, "employee_id": employee.id,
        "month": "2026-11",
    })
    assert page.status_code == 200
    soup = BeautifulSoup(page.text, "html.parser")
    form = soup.select_one("#labor-form")
    base = form.select_one('[data-quick-step="1"]')
    assert base is not None
    assert soup.select_one('form #labor-form') is None  # Solo un formulario laboral
    assert not form.select_one("section.dl-alert[data-salary-attendance]")
    assert not soup.select_one('.dl-alert[aria-label="Verificación de base salarial sin historial"]')
    attendance = base.select_one("[data-salary-attendance]")
    assert attendance is not None
    assert attendance.find("details") is not None and not attendance.find("details").has_attr("open")
    assert attendance.select_one('[name="period_start"]') is not None
    verification = base.select_one('[name="salary_base_verified"]')
    assert verification is not None
    assert verification.find_parent("details") is not None
    assert not verification.find_parent("details").has_attr("open")
    assert base.select_one('[name="salary"]') is not None
    assert form.select_one('[name="attendance_override"]') is not None


def test_wage_rate_field_is_optional_and_hidden_for_monthly_by_client_logic():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "app/templates/labor_workbench.html").read_text(encoding="utf-8")
    assert "showApplicableWageFields" in html
    assert '''basis?.value === "daily"''' in html
