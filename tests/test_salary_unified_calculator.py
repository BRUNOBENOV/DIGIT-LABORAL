"""Regresión del cálculo salarial único: mensualizado y jornalero."""
import pytest

from app.labor_calculator import CalculationError, calculate
from tests.test_labor_suite import salary, web_case


def test_salary_monthly_keeps_divisor_30():
    result = calculate(salary(salary="3044000", days_paid="30", pay_basis="monthly"))
    assert result["gross"] == 3_044_000
    assert result["net"] == 2_770_040
    assert {"label": "Modalidad salarial", "value": "Mensualizado · divisor 30"} in result["facts"]


def test_salary_daily_wage_alone_is_sufficient_for_18_paid_days():
    result = calculate(salary(
        salary="", pay_basis="daily", daily_rate="117077",
        days_paid="18", days_worked="18", hours_worked="144",
    ))
    assert result["gross"] == 2_107_386
    assert result["net"] == 1_917_721
    assert any(row["label"] == "Jornales del período"
               and row["amount"] == 2_107_386 for row in result["earnings"])
    assert any(row["label"] == "Base IPS" and "2.107.386" in row["value"]
               for row in result["facts"])


def test_salary_daily_zero_monthly_reference_is_not_a_required_salary():
    result = calculate(salary(
        salary="0", pay_basis="daily", daily_rate="117077", days_paid="18",
    ))
    assert result["gross"] == 2_107_386


def test_monthly_without_salary_still_fails_validation():
    with pytest.raises(CalculationError) as error:
        calculate(salary(salary="", pay_basis="monthly", days_paid="30"))
    assert error.value.field == "salary"


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


def test_salary_has_direct_save_action_before_first_calculate(web_case):
    from bs4 import BeautifulSoup
    client, db, box, company, employee, *_ = web_case
    response = client.get("/app/liquidaciones", params={
        "tipo": "salary", "month": "2026-10",
        "company_id": company.id, "employee_id": employee.id,
    })
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    actions = soup.select_one("[data-live-summary]")
    save = actions.select_one('button[data-save-current]')
    assert save is not None
    assert save.get("formaction") == "/app/liquidaciones/guardar"
    assert save.get("form") == "labor-form"
    assert not save.has_attr("disabled")
    assert actions.select_one("[data-quick-calculate]") is not None
    assert soup.select_one("#labor-document") is None
    # No mostrar un control muerto cuando todavía no hay documento calculado.
    assert "Ver documento completo" not in soup.select_one('[data-quick-step="5"]').get_text()


def test_salary_saves_draft_and_pdf_directly_with_no_ips_and_no_history(web_case):
    import json
    from sqlalchemy import select
    from pypdf import PdfReader
    import io
    from app.models import CalculationRecord
    from tests.test_labor_suite import token

    client, db, box, company, employee, *_ = web_case
    employee.ips_contributor = False
    employee.base_salary = 3_044_000
    db.commit()
    csrf = token(client, f"/app/liquidaciones?tipo=salary&company_id={company.id}&employee_id={employee.id}")
    payload = salary(
        csrf_token=csrf, company_id=str(company.id), employee_id=str(employee.id),
        month="2026-10", salary="3044000", pay_basis="monthly",
        days_paid="30", days_worked="27", hours_worked="216",
        period_start="2026-10-01", period_end="2026-10-31",
        apply_ips="", two_copies="on",
    )
    # Sin POST previo a /calcular: guardar debe recalcular y confirmar en servidor.
    response = client.post("/app/liquidaciones/guardar", data=payload, follow_redirects=False)
    assert response.status_code == 303, response.text[:300]
    db.expire_all()
    record = db.scalar(select(CalculationRecord).where(
        CalculationRecord.employee_id == employee.id,
        CalculationRecord.calculation_type == "suite_salary",
    ))
    assert record is not None
    assert record.reference_period == "2026-10"
    assert record.amount == 3_044_000
    assert record.status == "Borrador"
    saved_result = json.loads(record.result_json)
    assert saved_result["gross"] == 3_044_000
    assert saved_result["net"] == 3_044_000
    assert saved_result["copies"] == 2
    assert any("no hay historial salarial registrado" in note for note in saved_result["warnings"])
    assert any("No se aplicó descuento IPS" in note for note in saved_result["warnings"])

    page = client.get(response.headers["location"])
    assert page.status_code == 200 and "guardada" in page.text.lower()
    pdf = client.get(response.headers["location"] + "/exportar/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert len(PdfReader(io.BytesIO(pdf.content)).pages) >= 2


def test_direct_save_rejects_invalid_salary_without_creating_record(web_case):
    from sqlalchemy import select
    from app.models import CalculationRecord
    from tests.test_labor_suite import token

    client, db, _box, company, employee, *_ = web_case
    csrf = token(client, f"/app/liquidaciones?tipo=salary&company_id={company.id}&employee_id={employee.id}")
    response = client.post("/app/liquidaciones/guardar", data=salary(
        csrf_token=csrf, company_id=str(company.id), employee_id=str(employee.id),
        salary="-1", month="2026-10"
    ), follow_redirects=False)
    assert response.status_code == 422
    assert "Revisá los datos" in response.text
    db.expire_all()
    assert db.scalars(select(CalculationRecord).where(
        CalculationRecord.calculation_type == "suite_salary",
        CalculationRecord.employee_id == employee.id,
    )).all() == []



def test_jornalero_form_submits_with_only_daily_rate_and_valid_dates(web_case):
    from sqlalchemy import select
    from app.models import CalculationRecord
    from tests.test_labor_suite import token, salary as salary_inputs
    client, db, _box, company, employee, *_ = web_case
    csrf = token(client, f"/app/liquidaciones?tipo=salary&company_id={company.id}&employee_id={employee.id}")
    payload = salary_inputs(
        csrf_token=csrf, company_id=str(company.id), employee_id=str(employee.id),
        month="2026-10", pay_basis="daily", salary="", daily_rate="117077",
        days_paid="18", days_worked="18", hours_worked="144",
        period_start="2026-10-01", period_end="2026-10-31", apply_ips="on",
    )
    response = client.post("/app/liquidaciones/guardar", data=payload, follow_redirects=False)
    assert response.status_code == 303, response.text[:400]
    db.expire_all()
    record = db.scalar(select(CalculationRecord).where(
        CalculationRecord.employee_id == employee.id,
        CalculationRecord.calculation_type == "suite_salary",
    ))
    assert record is not None
    assert record.amount == 1_917_721
    assert record.reference_period == "2026-10"


def test_jornalero_page_only_requires_daily_wage_and_does_not_assume_26_paid_days():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "app/templates/labor_workbench.html").read_text(encoding="utf-8")
    assert "salaryInput.required = !jornalero" in html
    assert "jornalInput.required = jornalero" in html
    assert 'monthlySalaryField.style.display = jornalero ? "none" : ""' in html
    routes = (Path(__file__).resolve().parents[1] / "app/calculator_routes.py").read_text(encoding="utf-8")
    assert 'values["days_paid"] = "" if is_daily else "30"' in routes
    assert 'values["days_paid"] = "26" if is_daily' not in routes
