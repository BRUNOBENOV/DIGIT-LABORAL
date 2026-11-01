import json

from bs4 import BeautifulSoup
from fastapi import HTTPException
import pytest

from app import main as core
from app.calculator_presentation import calculation_summary
from app.labor_calculator import CalculationError, calculate
from app.models import CalculationRecord
from tests.test_labor_suite import token, web_case
from tests.test_payroll_average import average_case, selected_inputs
from tests.test_settlement_legal_cases import settlement_data, stability_data


def preset_data(**changes):
    values = settlement_data(settlement_preset_version="1", severance_regime="ordinary",
                             salary="3044000", average_salary="", notice_served="",
                             start_date="1999-02-11", end_date="2026-10-31")
    values.update(changes)
    return values


def test_default_ordinary_reference_computes_420_days_without_confirming_stability():
    inputs = preset_data()
    result = calculate(inputs)
    projection = result["settlement_projection"]
    assert (projection["status"], projection["units"], projection["days"], projection["notice_payable"]) == ("ordinary_reference",28,420,90)
    assert (projection["severance"], projection["notice"]) == (42_616_000,9_132_000)
    assert result["partial"]
    summary = calculation_summary(result)
    assert summary["values"]["severance"] == 42_616_000 and summary["values"]["notice"] == 9_132_000
    assert any("promedio no verificado" in fact["value"] for fact in result["facts"])
    assert any("estabilidad laboral" in warning for warning in result["warnings"])
    assert inputs["average_salary"] == "" and inputs["notice_served"] == ""


def test_ordinary_dismissal_without_stability_needs_no_double_indemnity_fields():
    result = calculate(preset_data(start_date="2019-01-01",end_date="2025-07-02"))
    assert not result["partial"]
    assert result["settlement_projection"]["status"] == "ordinary"
    assert result["settlement_projection"]["days"] == 105
    assert result["settlement_projection"]["notice_served"] == 0
    assert all("doble" not in row["label"].lower() for row in result["earnings"])


@pytest.mark.parametrize("reason",["resignation","justified"])
def test_non_payable_reasons_have_zero_projection_even_with_obsolete_hidden_inputs(reason):
    data = preset_data(reason=reason,average_salary="-1",notice_served="91",
                       stability_basis="worker_option",stability_evidence="Respaldo de otro escenario",stability_confirmed="on")
    result = calculate(data)
    p = result["settlement_projection"]
    assert p["status"] == "not_applicable"
    assert (p["days"],p["notice_payable"],p["severance"],p["notice"]) == (0,0,0,0)
    assert not any("Indemnización" in row["label"] for row in result["earnings"])
    assert not any("Fundamento declarado" == fact["label"] for fact in result["facts"])


@pytest.mark.parametrize("changes",[{"protected":"on"},{"indefinite":""},{"trial_completed":""}])
def test_presets_do_not_confirm_protection_contract_or_probation(changes):
    result = calculate(preset_data(**changes))
    assert result["partial"]
    assert result["settlement_projection"]["multiplier"] == 0
    assert not any("Indemnización" in row["label"] for row in result["earnings"])


@pytest.mark.parametrize("changes,field",[
    ({"stability_basis":""},"stability_basis"),
    ({"stability_evidence":""},"stability_evidence"),
    ({"stability_confirmed":""},"stability_confirmed"),
    ({"protected":"on"},"severance_regime"),
])
def test_double_indemnity_keeps_explicit_review_and_cannot_be_forced_by_presets(changes,field):
    data = stability_data(settlement_preset_version="1",**changes)
    with pytest.raises(CalculationError) as error: calculate(data)
    assert error.value.field == field


def test_manual_average_and_notice_are_preserved_until_the_reason_changes():
    result = calculate(preset_data(average_salary="3185221.66",average_from_salary="on",notice_served="20"))
    p=result["settlement_projection"]
    assert p["average"] == "3185221.66" and p["notice_payable"] == 70
    assert not any("promedio no verificado" in fact["value"] for fact in result["facts"])
    legacy = calculate(stability_data(severance_regime="auto"))
    assert legacy["partial"] and legacy["settlement_projection"]["days"] is None


def test_selected_employee_prefills_salary_suggestion_and_ordinary_without_legal_confirmation(web_case):
    client,db,_box,company,employee,_other=web_case
    employee.base_salary=3_044_000;db.commit()
    response=client.get(f"/app/liquidaciones?tipo=settlement&company_id={company.id}&employee_id={employee.id}")
    assert response.status_code == 200
    soup=BeautifulSoup(response.text,"html.parser")
    assert soup.select_one('[name="average_salary"]')["value"] == "3044000"
    assert soup.select_one('[name="average_from_salary"]')["value"] == "on"
    assert soup.select_one('[name="severance_regime"] option[selected]')["value"] == "ordinary"
    assert not soup.select_one('[name="stability_confirmed"]').has_attr("checked")
    assert "Sugerido del legajo. Modificar si es necesario" in soup.select_one("[data-average-salary-hint]").text
    assert soup.select_one('[data-save-current]').has_attr('disabled')


def test_live_reference_can_save_a_traceable_draft_but_cannot_be_approved_as_final(web_case):
    client,db,_box,company,employee,_other=web_case
    values=preset_data(company_id=company.id,employee_id=employee.id,csrf_token=token(client))
    before=db.query(CalculationRecord).count()
    preview=client.post('/app/liquidaciones/calcular',data=values,headers={'Accept':'application/json'})
    assert preview.status_code == 200 and preview.json()['partial']
    assert preview.json()['values']['severance'] == 42_616_000
    assert db.query(CalculationRecord).count() == before
    saved=client.post('/app/liquidaciones/guardar',data=values,follow_redirects=False)
    assert saved.status_code == 303
    record=db.query(CalculationRecord).filter_by(employee_id=employee.id).one()
    inputs=json.loads(record.input_json)
    assert inputs['average_salary']=='3044000' and inputs['average_from_salary']=='on'
    assert inputs['notice_served']=='0' and inputs['severance_regime']=='ordinary'
    assert inputs['stability_confirmed']=='' and record.status=='Borrador'
    with pytest.raises(HTTPException) as error: core._revalidate_calculation_before_approval(record,db)
    assert error.value.status_code==409
    copied=client.get(f'/app/liquidaciones/{record.id}/copiar')
    assert 'value="ordinary" selected' in copied.text
    assert 'value="3044000"' in copied.text


def test_preset_does_not_replace_a_reviewed_payroll_average(average_case):
    client,db,_box,_company,_employee,*_=average_case
    values=selected_inputs(average_case)
    values.update(settlement_preset_version='1',average_from_salary='on')
    response=client.post('/app/liquidaciones/guardar',data=values,follow_redirects=False)
    assert response.status_code==303
    record=db.query(CalculationRecord).one()
    data=json.loads(record.input_json)
    assert data['average_origin']=='payroll' and data['average_salary']=='3610000.17'
    assert data['average_from_salary']==''
    assert json.loads(record.result_json)['average_provenance']['average_salary']=='3610000.17'


def test_projection_is_available_without_inventing_annual_remuneration(web_case):
    client,db,*_=web_case
    values=preset_data(annual_remuneration='',csrf_token=token(client))
    response=client.post('/herramientas/liquidacion/previsualizar',data=values)
    assert response.status_code==200 and response.json()['days']==420
    result=client.post('/herramientas/calcular',data=values,headers={'Accept':'application/json'})
    assert result.status_code==422 and result.json()['field']=='annual_remuneration'
    assert db.query(CalculationRecord).count()==0


def test_presets_retain_csrf_and_employee_scope(web_case):
    client,_db,_box,company,_employee,other=web_case
    values=preset_data(company_id=company.id,employee_id=other.id,csrf_token=token(client))
    assert client.post('/app/liquidaciones/calcular',data=values,headers={'Accept':'application/json'}).status_code==404
    values.pop('csrf_token')
    assert client.post('/herramientas/calcular',data=values,headers={'Accept':'application/json'}).status_code==403


def test_documenting_a_protected_case_does_not_auto_select_or_confirm_double_indemnity():
    result=calculate(preset_data(protected='on',protection_basis='Fuero declarado para prueba',
                                 protection_evidence='Expediente sintético pendiente de revisión'))
    assert result['partial'] and result['settlement_projection']['status']=='special'
    assert result['settlement_projection']['multiplier']==0
    assert any(fact['label']=='Fundamento de protección declarado' for fact in result['facts'])
    assert any('Expediente sintético' in note for note in result['notes'])
