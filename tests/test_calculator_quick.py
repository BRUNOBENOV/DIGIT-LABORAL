from bs4 import BeautifulSoup
import pytest

from app.calculator_fields import GROUPS
from app.labor_calculator import calculate
from app.models import CalculationRecord, EmployeeExit
from tests.test_labor_suite import salary, settlement, token, web_case
from tests.test_settlement_legal_cases import stability_data
from tests.test_payroll_average import average_case, selected_inputs


@pytest.mark.parametrize("kind", ["salary", "settlement"])
def test_compact_form_preserves_every_field_with_only_the_base_step_open(web_case, kind):
    client, _db, _box, company, employee, _other = web_case
    for path in (f"/herramientas?tipo={kind}",
                 f"/app/liquidaciones?tipo={kind}&company_id={company.id}&employee_id={employee.id}"):
        response = client.get(path)
        assert response.status_code == 200
        soup = BeautifulSoup(response.text, "html.parser")
        form = soup.select_one("#labor-form")
        steps = form.select("[data-quick-step]")
        assert len(steps) == 5
        assert [s["data-quick-step"] for s in steps if s.has_attr("open")] == ["1"]
        for group in GROUPS[kind]:
            for field in group["fields"]:
                assert len(form.select(f'[name="{field["name"]}"]')) == 1, field["name"]
        ids = [node["id"] for node in soup.select("[id]")]
        assert len(ids) == len(set(ids))
        summary = soup.select_one("[data-live-summary]")
        assert summary.select_one('[data-summary-value="net"]').text == "—"
        assert soup.select_one("[data-quick-calculate]")["form"] == "labor-form"
        assert "F6" in summary.text
        if kind == "settlement" and path.startswith("/app"):
            assert not form.select_one(".dl-average-disclosure").has_attr("open")
            assert form.select_one('[name="annual_remuneration"]').has_attr("required")


def test_server_validation_opens_the_relevant_nested_step_without_losing_inputs(web_case):
    client, *_ = web_case
    values = settlement(aguinaldo_paid="20000", csrf_token=token(client))
    values["annual_remuneration"] = "1"
    response = client.post("/herramientas/calcular", data=values)
    assert response.status_code == 422
    soup = BeautifulSoup(response.text, "html.parser")
    assert soup.select_one('[data-quick-step="3"]').has_attr("open")
    assert soup.select_one('[data-concept-editor="aguinaldo"]').has_attr("open")
    assert soup.select_one('[name="aguinaldo_paid"]')["value"] == "20000"
    assert soup.select_one("#labor-error") is not None


@pytest.mark.parametrize("case", ["salary", "ordinary", "partial", "double"])
def test_live_summary_uses_the_engine_and_never_saves_or_closes_an_exit(web_case, case):
    client, db, _box, company, employee, _other = web_case
    values = (salary(day_extra_hours="2", commissions="40000") if case == "salary" else
              stability_data(annual_remuneration="19037824", proportional_days="22") if case == "double" else
              stability_data(severance_regime="auto", annual_remuneration="19037824") if case == "partial" else settlement())
    expected = calculate(values)
    before = (db.query(CalculationRecord).count(), db.query(EmployeeExit).count())
    values.update(csrf_token=token(client), company_id=company.id, employee_id=employee.id)
    response = client.post("/app/liquidaciones/calcular", data=values, headers={"Accept":"application/json"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["net"], result["gross"], result["discounts"], result["partial"]) == (
        expected["net"], expected["gross"], expected["discounts"], expected["partial"])
    v = result["values"]
    assert sum(v[k] for k in ("salary", "aguinaldo", "vacations", "severance", "notice", "other")) == result["gross"]
    assert v["ips"] + v["other_discounts"] == result["discounts"]
    if case == "double":
        assert (v["severance"], v["notice"], result["net"]) == (89186206, 9555665, 102560623)
    if case == "partial":
        assert result["label"] == "Subtotal parcial" and v["severance"] == 0
    assert "identity" not in result and "average_provenance" not in result
    assert "no-store" in response.headers["cache-control"]
    assert before == (db.query(CalculationRecord).count(), db.query(EmployeeExit).count())


def test_live_summary_keeps_csrf_tenant_and_legal_confirmation_validation(web_case):
    client, _db, _box, company, employee, other = web_case
    values = stability_data(stability_confirmed="", csrf_token=token(client), company_id=company.id, employee_id=employee.id)
    headers = {"Accept":"application/json"}
    response = client.post("/app/liquidaciones/calcular", data=values, headers=headers)
    assert response.status_code == 422 and response.json()["field"] == "stability_confirmed"
    values["employee_id"] = other.id
    assert client.post("/app/liquidaciones/calcular", data=values, headers=headers).status_code == 404
    values.pop("csrf_token")
    assert client.post("/herramientas/calcular", data=values, headers=headers).status_code == 403


def test_live_summary_revalidates_payroll_sources(average_case):
    client, _db, *_ = average_case
    values = selected_inputs(average_case)
    headers = {"Accept":"application/json"}
    assert client.post("/app/liquidaciones/calcular", data=values, headers=headers).status_code == 200
    values["average_salary"] = "9999999"
    response = client.post("/app/liquidaciones/calcular", data=values, headers=headers)
    assert response.status_code == 422 and response.json()["field"] == "average_salary"


def test_calculated_document_and_manual_editors_remain_available_without_javascript(web_case):
    client, *_ = web_case
    values = settlement(proportional_days="22", csrf_token=token(client))
    response = client.post("/herramientas/calcular", data=values)
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    assert soup.select_one('[data-concept-amount="vacations"]').text == "Gs. 2.200.000"
    assert soup.select_one('[data-concept-amount="aguinaldo"]').text == "Gs. 1.500.000"
    assert "Modificar a mano" in soup.select_one('[data-concept-editor="vacations"] summary').text
    document = soup.select_one("#labor-document")
    assert document is not None and not document.has_attr("open")
    assert document.select_one("#labor-result") is not None
    assert document.select_one('[formaction="/herramientas/exportar/pdf"]') is not None
    assert soup.select_one("#labor-form [type=submit]") is not None
