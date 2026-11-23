import io
import json

import pytest
from fastapi import HTTPException
from pypdf import PdfReader

from app import main as core
from app.labor_calculator import SOURCE, calculate
from app.models import CalculationRecord
from tests.test_labor_suite import token, web_case
from tests.test_settlement_legal_cases import settlement_data, stability_data


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


@pytest.mark.parametrize("pending", ["promedio", "vacaciones"])
def test_monthly_draft_requires_review_before_approval_and_matches_its_receipt(web_case, pending):
    client, db, _box, company, employee, _ = web_case
    csrf = token(client)
    headers = {"X-CSRF-Token": csrf}
    reviewed = settlement_data(
        settlement_preset_version="2", pay_basis="monthly", company_id=str(company.id),
        employee_id=str(employee.id), csrf_token=csrf, start_date="2023-01-13",
        end_date="2026-11-21", issued_date="2026-11-21", salary="3044000",
        average_salary="2950407.80", annual_remuneration="15353468.29", proportional_days="10",
    )
    incomplete = (dict(reviewed, average_salary="3044000", average_from_salary="on")
                  if pending == "promedio" else dict(reviewed, pending_days="", double_days="", proportional_days=""))
    preview = client.post("/app/liquidaciones/calcular", data=incomplete, headers={"Accept": "application/json"})
    assert preview.status_code == 200 and preview.json()["partial"]
    assert any(pending in message.lower() for message in preview.json()["warnings"])
    saved = client.post("/app/liquidaciones/guardar", data=incomplete, follow_redirects=False)
    assert saved.status_code == 303
    record = db.query(CalculationRecord).filter_by(employee_id=employee.id).one()
    endpoint = f"/api/calculations/{record.id}"
    approval = client.patch(endpoint, json={"status": "Aprobado"}, headers=headers)
    assert approval.status_code == 409 and "subtotal parcial" in approval.text.lower()
    db.refresh(record)
    assert record.status == "Borrador"
    draft = client.get(f"/app/liquidaciones/{record.id}/exportar/csv")
    assert draft.status_code == 200 and "Subtotal parcial" in draft.text

    updated = client.put(endpoint, json=reviewed, headers=headers)
    assert updated.status_code == 200
    result = updated.json()["result"]
    assert not result["partial"]
    projection = result["settlement_projection"]
    assert (projection["days"], projection["notice_payable"]) == (60, 45)
    assert {row["label"]: row["amount"] for row in result["earnings"]} == {
        "Indemnización ordinaria por antigüedad": 5_900_816,
        "Indemnización por preaviso no cumplido": 4_425_612,
        "Vacaciones proporcionales": 1_014_667,
        "Aguinaldo devengado": 1_279_456,
    }
    assert next(row["formula"] for row in result["earnings"] if row["label"] == "Aguinaldo devengado") == "Gs. 15.353.468,29 / 12"
    approved = client.patch(endpoint, json={"status": "Aprobado"}, headers=headers)
    assert approved.status_code == 200 and approved.json()["status"] == "Aprobado"
    assert approved.json()["amount"] == 12_620_551
    pdf = client.get(f"/app/liquidaciones/{record.id}/exportar/pdf")
    assert pdf.status_code == 200
    pages = PdfReader(io.BytesIO(pdf.content)).pages
    assert "Neto a percibir: Gs. 12.620.551" in "\n".join(page.extract_text() for page in pages)


def test_reviewed_zero_and_manually_confirmed_identical_salary_are_accepted():
    data = settlement_data(settlement_preset_version="2", average_from_salary="on",
                           average_salary_reviewed="on", pending_days="0", double_days="0", proportional_days="0")
    result = calculate(data)
    assert not result["partial"]
    assert any("cotejó el promedio" in fact["value"] for fact in result["facts"])
    assert calculate(dict(data, average_salary=""))["partial"]
    assert calculate(dict(data, proportional_days=""))["partial"]
    assert not calculate(dict(data, reason="resignation", proportional_days=""))["partial"]


def test_aguinaldo_preview_keeps_fractional_annual_basis_until_final_rounding(web_case):
    client, *_ = web_case
    data = settlement_data(annual_remuneration="15000005.51", csrf_token=token(client))
    preview = client.post("/herramientas/aguinaldo/previsualizar", data=data)
    assert preview.status_code == 200 and preview.json()["aguinaldo_accrued"] == 1_250_000
    row = next(row for row in calculate(data)["earnings"] if row["label"] == "Aguinaldo devengado")
    assert row["amount"] == preview.json()["aguinaldo_accrued"] and "15.000.005,51" in row["formula"]
