import io
import json

import pytest
from fastapi import HTTPException
from pypdf import PdfReader

from app import main as core
from app.labor_calculator import SOURCE, calculate
from app.models import CalculationRecord
from tests.test_labor_suite import token, web_case
from tests.test_settlement_legal_cases import stability_data


def test_private_and_public_forms_expose_stability_resolution_and_default_zero(web_case):
    client, _db, _box, company, employee, _other = web_case
    for path in (
        "/herramientas?tipo=settlement",
        f"/app/liquidaciones?tipo=settlement&company_id={company.id}&employee_id={employee.id}",
        "/herramientas/comparar?tipo=settlement",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert "Indemnización y preaviso" in response.text
        assert 'value="stability_double"' in response.text
        assert 'data-settlement-value="days"' in response.text
        assert "settlement-preview.js?v=" in response.text
        assert 'step="0.01"' in response.text
    page = client.get("/herramientas?tipo=settlement").text
    assert 'name="notice_served" type="number" value="0"' in page


def test_preview_uses_same_engine_without_saving_or_confirming_any_exit(web_case):
    client, db, *_ = web_case
    before = db.query(CalculationRecord).count()
    values = stability_data(stability_basis="", stability_evidence="", stability_confirmed="")
    values["csrf_token"] = token(client)
    response = client.post("/herramientas/liquidacion/previsualizar", data=values)
    assert response.status_code == 200, response.text
    data = response.json()
    assert (data["units"], data["days"], data["notice_payable"]) == (28, 840, 90)
    assert (data["severance"], data["notice"]) == (89_186_206, 9_555_665)
    assert "no-store" in response.headers["cache-control"]
    assert "Acta" not in response.text and "employer" not in data
    assert db.query(CalculationRecord).count() == before
    values["notice_served"] = "91"
    error = client.post("/herramientas/liquidacion/previsualizar", data=values)
    assert error.status_code == 422 and error.json()["field"] == "notice_served"


def test_calculate_reports_missing_confirmation_then_renders_days_and_totals(web_case):
    client, _db, _box, company, employee, _ = web_case
    values = stability_data(
        company_id=str(company.id), employee_id=str(employee.id),
        annual_remuneration="19037824", proportional_days="22", stability_confirmed="",
    )
    values["csrf_token"] = token(client)
    invalid = client.post("/app/liquidaciones/calcular", data=values)
    assert invalid.status_code == 422
    assert "Confirmá la revisión del fundamento" in invalid.text
    assert 'name="stability_basis"' in invalid.text and "worker_option" in invalid.text
    values["stability_confirmed"] = "on"
    response = client.post("/app/liquidaciones/calcular", data=values)
    assert response.status_code == 200
    assert "Indemnización doble por estabilidad" in response.text
    assert "102.560.623" in response.text and "89.186.206" in response.text
    assert "Días de indemnización</dt><dd>840" in response.text
    assert "Días de preaviso a pagar</dt><dd>90" in response.text
    assert "Subtotal parcial</span>" not in response.text


def test_confirmed_regime_survives_save_copy_revalidation_and_exports(web_case):
    client, db, _box, company, employee, _ = web_case
    values = stability_data(company_id=str(company.id), employee_id=str(employee.id))
    values["csrf_token"] = token(client)
    response = client.post("/app/liquidaciones/guardar", data=values, follow_redirects=False)
    assert response.status_code == 303
    calc = db.query(CalculationRecord).filter_by(employee_id=employee.id).one()
    inputs, result = json.loads(calc.input_json), json.loads(calc.result_json)
    assert inputs["stability_basis"] == "worker_option"
    assert inputs["stability_confirmed"] == "on"
    assert inputs["average_salary"] == "3185221.66"
    assert result["settlement_projection"]["days"] == 840
    assert calc.amount == 98_741_871
    core._revalidate_calculation_before_approval(calc, db)
    copied = client.get(f"/app/liquidaciones/{calc.id}/copiar")
    assert copied.status_code == 200
    assert 'value="stability_double" selected' in copied.text
    assert "Acta sintética" in copied.text
    pdf = client.get(f"/app/liquidaciones/{calc.id}/exportar/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Días de indemnización: 840" in text
    assert "98.741.871" in text and "Acta sintética" in text
    csv = client.get(f"/app/liquidaciones/{calc.id}/exportar/csv")
    assert csv.status_code == 200
    assert "Indemnización doble por estabilidad" in csv.text and "89186206" in csv.text


def test_unresolved_subtotal_cannot_be_approved_as_complete_settlement(web_case):
    _client, db, _box, company, employee, _ = web_case
    inputs = stability_data(severance_regime="auto", annual_remuneration="19037824")
    result = calculate(inputs)
    assert result["net"] == 1_586_485 and result["partial"]
    record = CalculationRecord(
        company_id=company.id, employee_id=employee.id,
        calculation_type="suite_settlement", reference_period="2026-10-31",
        input_json=json.dumps(inputs), result_json=json.dumps(result), amount=result["net"],
        source=SOURCE, status="Borrador", created_by="Contador sintético",
    )
    with pytest.raises(HTTPException) as error:
        core._revalidate_calculation_before_approval(record, db)
    assert error.value.status_code == 409
    assert "subtotal parcial" in error.value.detail
