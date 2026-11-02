from datetime import date
import hashlib
import io
import json

from bs4 import BeautifulSoup
from fastapi import HTTPException
from pypdf import PdfReader
import pytest
from sqlalchemy import select

from app import main as core
from app.labor_calculator import CalculationError, calculate, completed_years, settlement_projection
from app.models import CalculationRecord, Document
from app.settlement_presets import service_years, settlement_defaults
from tests.test_labor_suite import token, web_case
from tests.test_settlement_legal_cases import settlement_data


def scenario(**changes):
    data = settlement_data(settlement_preset_version="2", severance_regime="ordinary",
        start_date="1999-02-11", end_date="2026-10-31", salary="3044000", average_salary="3044000",
        annual_remuneration="19037824")
    data.update(changes)
    return data


@pytest.mark.parametrize("start,end,years,double", [
    ("2016-10-31","2026-10-30",9,False), ("2016-10-31","2026-10-31",10,True),
    ("2016-10-31","2026-11-01",10,True), ("2016-02-29","2026-02-27",9,False),
    ("2016-02-29","2026-02-28",10,True), ("2016-02-29","2026-03-01",10,True),
    ("2017-01-01","2026-07-02",9,False),
])
def test_stability_uses_ten_complete_anniversaries_not_rounded_indemnity_units(start,end,years,double):
    data = scenario(start_date=start,end_date=end)
    source = dict(data)
    normalized = settlement_defaults(data)
    assert data == source
    assert service_years(data) == completed_years(date.fromisoformat(start),date.fromisoformat(end)) == years
    assert normalized["severance_regime"] == ("stability_double" if double else "ordinary")
    p = settlement_projection(data)
    assert p["stability_detected"] == double and p["multiplier"] == (2 if double else 1)


def test_derlis_dates_propose_840_days_as_conditional_not_confirmed_legal_facts():
    values = scenario()
    result = calculate(values)
    p = result["settlement_projection"]
    assert (p["years"],p["units"],p["days"],p["notice_payable"]) == (27,28,840,90)
    assert (p["severance"],p["notice"]) == (85_232_000,9_132_000)
    assert result["partial"] and p["status"] == "stability_double_pending"
    assert any(row["amount"] == 85_232_000 and "escenario condicionado" in row["label"] for row in result["earnings"])
    assert not any(fact["label"] in {"Régimen indemnizatorio confirmado", "Fundamento declarado"} for fact in result["facts"])
    assert any("pendiente de documentar" in warning for warning in result["warnings"])
    normalized = settlement_defaults(values)
    assert not normalized["stability_confirmed"] and not normalized["stability_basis"] and not normalized["stability_evidence"]


@pytest.mark.parametrize("changes", [{"protected":"on"},{"indefinite":""},{"trial_completed":""}])
def test_automatic_double_never_bypasses_another_protection_or_missing_contract_facts(changes):
    data = scenario(**changes)
    result = calculate(data)
    assert result["partial"] and result["settlement_projection"]["multiplier"] == 0
    assert not any("Indemnización" in row["label"] for row in result["earnings"])


@pytest.mark.parametrize("reason", ["resignation","justified","worker_justified","death","mutual_consent"])
def test_age_does_not_turn_other_exit_reasons_into_double_indemnity(reason):
    result = calculate(scenario(reason=reason))
    assert result["settlement_projection"]["status"] not in {"stability_double", "stability_double_pending"}
    assert not any("doble" in row["label"].lower() for row in result["earnings"])


def test_confirming_the_double_requires_real_declared_basis_and_reference():
    for missing in ["stability_basis","stability_evidence"]:
        data = scenario(stability_confirmed="on",stability_basis="worker_option",stability_evidence="Acta sintética: opción del trabajador documentada y revisada")
        data[missing] = ""
        with pytest.raises(CalculationError) as error: calculate(data)
        assert error.value.field == missing
    result = calculate(scenario(stability_confirmed="on",stability_basis="worker_option",stability_evidence="Acta sintética: opción del trabajador documentada y revisada"))
    assert not result["partial"] and result["settlement_projection"]["status"] == "stability_double"
    assert result["settlement_projection"]["severance"] == 85_232_000


def test_legacy_values_remain_partial_ordinary_reference_and_explicit_review_stays_available():
    old = calculate(scenario(settlement_preset_version="1"))
    assert old["partial"] and old["settlement_projection"]["days"] == 420
    explicit = calculate(scenario(severance_regime="auto"))
    assert explicit["partial"] and explicit["settlement_projection"]["days"] is None


def scoped_scenario(case, **changes):
    client, _db, _box, company, employee, *_ = case
    return scenario(company_id=str(company.id),employee_id=str(employee.id),csrf_token=token(client),**changes)


def test_fresh_private_page_selects_double_without_checking_other_protections(web_case):
    client,db,_box,company,employee,*_ = web_case
    employee.admission_date=date(1999,2,11); employee.contract_type="Tiempo indefinido"; employee.base_salary=3_044_000; db.commit()
    response = client.get("/app/liquidaciones",params=dict(tipo="settlement",company_id=company.id,employee_id=employee.id))
    assert response.status_code == 200
    soup = BeautifulSoup(response.text,"html.parser")
    assert soup.select_one('[name="settlement_preset_version"]')["value"] == "2"
    assert soup.select_one('[name="severance_regime"] option[selected]')["value"] == "stability_double"
    assert not soup.select_one('[name="protected"]').has_attr("checked")
    assert not soup.select_one('[name="stability_confirmed"]').has_attr("checked")
    assert soup.select_one('[name="stability_evidence"]').text == ""
    assert soup.select_one('[data-stability-detected]') is not None


def test_partial_double_saves_draft_but_cannot_be_approved_by_either_route(web_case):
    client,db,*_ = web_case
    data = scoped_scenario(web_case)
    preview = client.post("/app/liquidaciones/calcular",data=data,headers={"Accept":"application/json"})
    assert preview.status_code == 200 and preview.json()["partial"]
    assert preview.json()["values"]["severance"] == 85_232_000
    saved = client.post("/api/calculations",json=data,headers={"X-CSRF-Token":data["csrf_token"]})
    assert saved.status_code == 201, saved.text
    item = db.get(CalculationRecord,saved.json()["id"])
    assert item.status == "Borrador" and json.loads(item.input_json)["severance_regime"] == "stability_double"
    with pytest.raises(HTTPException) as error: core._revalidate_calculation_before_approval(item,db)
    assert error.value.status_code == 409
    assert client.patch(f"/api/calculations/{item.id}",json={"status":"Aprobado"},headers={"X-CSRF-Token":data["csrf_token"]}).status_code == 409


@pytest.fixture
def judicial_case(web_case):
    client,db,box,company,employee,other = web_case
    employee.admission_date=date(1999,2,11); employee.contract_type="Tiempo indefinido"
    document = Document(company_id=company.id,employee_id=employee.id,category="Sentencia laboral",title="Sentencia sintética",
        stored_name="documents/synthetic.pdf",original_name="sentencia-sintetica.pdf",content_type="application/pdf",content_bytes=b"%PDF-1.4 Synthetic court document for automated tests")
    db.add(document); db.commit()
    data = scoped_scenario(web_case,reason="justified",judicial_confirmed="on",judicial_date="2026-10-30",
        judicial_reference="Juzgado sintético, expediente 123, sentencia firme y ejecutoriada previa al despido",judicial_document_id=str(document.id))
    return client,db,box,company,employee,other,document,data


def test_judicial_cause_has_zero_severance_and_notice_and_records_scoped_attachment(judicial_case):
    client,db,_box,_company,_employee,_other,document,data = judicial_case
    response = client.post("/api/calculations",json=data,headers={"X-CSRF-Token":data["csrf_token"]})
    assert response.status_code == 201, response.text
    item = db.get(CalculationRecord,response.json()["id"])
    result = json.loads(item.result_json)
    assert result["settlement_projection"]["severance"] == result["settlement_projection"]["notice"] == 0
    assert not result["partial"]
    assert result["judicial_provenance"]["document_id"] == document.id
    assert result["judicial_provenance"]["sha256"] == hashlib.sha256(document.content_bytes).hexdigest()
    core._revalidate_calculation_before_approval(item,db)
    approved = client.patch(f"/api/calculations/{item.id}",json={"status":"Aprobado"},headers={"X-CSRF-Token":data["csrf_token"]})
    assert approved.status_code == 200


def test_public_or_forged_verification_flag_cannot_resolve_the_judicial_review(judicial_case):
    _client,_db,_box,_company,_employee,_other,_document,data = judicial_case
    result = calculate(dict(data,judicial_evidence_verified="true",_judicial_document_verified="true"))
    assert result["partial"]


@pytest.mark.parametrize("change",["missing","foreign_employee","foreign_company","empty","type","not_available","oversized_id"])
def test_judicial_exception_requires_available_document_for_same_employee_and_company(judicial_case,monkeypatch,change):
    client,db,_box,_company,_employee,other,document,data = judicial_case
    if change == "missing": data["judicial_document_id"]=""
    elif change == "foreign_employee": document.employee_id=other.id
    elif change == "foreign_company": document.company_id=other.company_id
    elif change == "empty": document.content_bytes=b""
    elif change == "type": document.content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif change == "not_available": document.content_bytes=None
    elif change == "oversized_id": data["judicial_document_id"]="9"*100
    db.commit()
    response = client.post("/app/liquidaciones/calcular",data=data,headers={"Accept":"application/json"})
    assert response.status_code == 422, response.text
    assert response.json()["field"] == "judicial_document_id"
    assert db.scalar(select(CalculationRecord.id)) is None


@pytest.mark.parametrize("changes,field", [({"judicial_date":"2026-11-01"},"judicial_date"),
    ({"judicial_date":"1998-12-31"},"judicial_date"),({"judicial_date":""},"judicial_date"),
    ({"judicial_reference":""},"judicial_reference"),({"start_date":"2020-01-01"},"judicial_confirmed")])
def test_judicial_dates_and_reference_are_validated(judicial_case,changes,field):
    client,_db,_box,_company,_employee,_other,_document,data = judicial_case
    response = client.post("/app/liquidaciones/calcular",data=dict(data,**changes),headers={"Accept":"application/json"})
    assert response.status_code == 422 and response.json()["field"] == field


def test_changed_judicial_file_blocks_recalculation_and_approval_but_reprint_keeps_original(judicial_case):
    client,db,_box,_company,_employee,_other,document,data = judicial_case
    saved = client.post("/api/calculations",json=data,headers={"X-CSRF-Token":data["csrf_token"]})
    item = db.get(CalculationRecord,saved.json()["id"])
    inputs = json.loads(item.input_json)
    original = json.loads(item.result_json)
    pdf = client.get(f"/app/liquidaciones/{item.id}/exportar/pdf")
    original_text="".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    document.content_bytes=b"%PDF Changed synthetic document"; db.commit()
    response = client.post("/app/liquidaciones/calcular",data=dict(inputs,csrf_token=data["csrf_token"]),headers={"Accept":"application/json"})
    assert response.status_code == 422 and response.json()["field"] == "judicial_document_id"
    with pytest.raises(HTTPException) as error: core._revalidate_calculation_before_approval(item,db)
    assert error.value.status_code == 409
    reprint=client.get(f"/app/liquidaciones/{item.id}/exportar/pdf")
    assert "".join(page.extract_text() for page in PdfReader(io.BytesIO(reprint.content)).pages) == original_text
    db.refresh(item); assert json.loads(item.result_json) == original


def test_document_picker_is_scoped_bounded_and_preserves_an_older_selected_document(judicial_case):
    client,db,_box,company,employee,other,document,_data = judicial_case
    for index in range(55):
        db.add(Document(company_id=company.id,employee_id=employee.id,title=f"Documento sintético {index}",stored_name=f"{index}.pdf",original_name=f"{index}.pdf",content_type="application/pdf",content_bytes=b"Synthetic"))
    db.commit()
    url="/api/liquidaciones/documentos-judiciales"
    response=client.get(url,params=dict(company_id=company.id,employee_id=employee.id,document_id=document.id))
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert len(response.json()["items"]) == 51 and document.id in [item["id"] for item in response.json()["items"]]
    assert client.get(url,params=dict(company_id=company.id,employee_id=other.id)).status_code == 404
    assert client.get(url,params=dict(company_id=other.company_id,employee_id=other.id)).status_code == 404


def test_document_upload_flow_can_link_real_uploaded_bytes_to_a_judicial_exception(web_case,tmp_path,monkeypatch):
    from app.storage_service import LocalStorage
    client,db,_box,company,employee,*_ = web_case
    employee.admission_date=date(1999,2,11); db.commit()
    monkeypatch.setattr(core,"storage",LocalStorage(tmp_path))
    data=scoped_scenario(web_case,reason="justified",judicial_confirmed="on",judicial_date="2026-10-30",
                         judicial_reference="Juzgado sintético, sentencia firme revisada antes del despido")
    uploaded=client.post("/app/documents",data=dict(csrf_token=data["csrf_token"],company_id=company.id,employee_id=employee.id,title="Sentencia sintética",category="Sentencia laboral"),
                         files={"file":("sentencia.pdf",b"%PDF-1.4 Synthetic court document","application/pdf")},follow_redirects=False)
    assert uploaded.status_code == 303
    document=db.scalar(select(Document).where(Document.employee_id==employee.id))
    data["judicial_document_id"]=str(document.id)
    response=client.post("/app/liquidaciones/calcular",data=data,headers={"Accept":"application/json"})
    assert response.status_code == 200 and response.json()["values"]["severance"] == response.json()["values"]["notice"] == 0
    assert not response.json()["partial"]
