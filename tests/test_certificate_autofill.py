import io
import json
import re
from datetime import date

import pytest
from docx import Document
from pypdf import PdfReader
from sqlalchemy import func, select

from app.certificate_autofill import certificate_dossier_data
from app.document_export import decode_metadata
from app.models import Branch, CompanySection, EmployeeComplianceProfile, GeneratedCertificate, SalaryHistory
from tests.test_labor_suite import token, web_case


@pytest.fixture
def dossier_case(web_case):
    client, db, box, company, employee, other = web_case
    company.address = "Domicilio legal 10"
    company.work_location = "Establecimiento registrado 20"
    company.legal_representative = "Representante sintético"
    branch = Branch(company_id=company.id, name="Sucursal asignada", address="Sucursal 30")
    section = CompanySection(company_id=company.id, name="Administración")
    db.add_all([branch, section]); db.flush()
    employee.branch_id = branch.id
    employee.section_id = section.id
    employee.position = "COBRADOR"
    employee.admission_date = date(1999, 2, 11)
    employee.birth_date = date(1980, 11, 2)
    employee.address = "Domicilio personal 40"
    employee.base_salary = 4_500_000
    employee.notes = "Notas de migración: no son funciones ni horarios pactados."
    db.add(EmployeeComplianceProfile(
        employee_id=employee.id, sex="Masculino", marital_status="Soltero/a", nationality="Paraguaya",
        profession="Auxiliar administrativo", work_schedule="Lunes a viernes, 08:00 a 17:00",
    ))
    db.add_all([
        SalaryHistory(employee_id=employee.id, previous_salary=0, new_salary=3_044_000, effective_from=date(2026, 1, 1)),
        SalaryHistory(employee_id=employee.id, previous_salary=3_044_000, new_salary=4_500_000, effective_from=date(2027, 1, 1)),
    ])
    db.commit()
    return web_case


def suggestion(client, company, employee, issued="2026-11-02"):
    return client.get("/api/certificates/autofill", params={
        "company_id": company.id, "employee_id": employee.id, "issue_date": issued,
    })


def contract_data(client, company, employee):
    return {
        **suggestion(client, company, employee).json()["fields"],
        "csrf_token": token(client), "company_id": str(company.id), "employee_id": str(employee.id),
        "document_type": "contrato_trabajo", "issue_date": "2026-11-02", "dossier_submission": "1",
        "job_functions": "Gestión de cobranzas documentadas", "weekly_rest": "Domingo",
        "contract_payment_method": "Transferencia bancaria", "intent": "generate_contract",
    }


def test_dossier_endpoint_maps_fields_dates_and_provenance_without_writes(dossier_case):
    client, db, _, company, employee, _ = dossier_case
    before = employee.updated_at
    profiles = db.scalar(select(func.count()).select_from(EmployeeComplianceProfile))
    response = suggestion(client, company, employee)
    assert response.status_code == 200
    assert response.headers["cache-control"].startswith("no-store")
    payload = response.json()
    assert payload["fields"]["position"] == "COBRADOR"
    assert payload["fields"]["salary"] == "3044000"  # Future salary is not in force yet.
    assert payload["fields"]["admission_date"] == "1999-02-11"
    assert payload["fields"]["contract_worker_age"] == "46"
    assert payload["fields"]["contract_worker_civil_status"] == "Soltero/a"
    assert payload["fields"]["work_schedule"] == "Lunes a viernes, 08:00 a 17:00"
    assert payload["fields"]["workplace"] == "Sucursal 30"
    assert payload["fields"]["employee_section"] == "Administración"
    assert payload["fields"]["employee_profession"] == "Auxiliar administrativo"
    assert payload["sources"]["workplace"] == "Sucursal asignada al funcionario"
    assert payload["fields"]["job_functions"] == ""
    assert payload["fields"]["contract_payment_method"] == ""
    assert "job_functions" in payload["missing_fields"]
    db.refresh(employee)
    assert employee.updated_at.replace(tzinfo=None) == before.replace(tzinfo=None)
    assert db.scalar(select(func.count()).select_from(EmployeeComplianceProfile)) == profiles
    assert not db.scalar(select(GeneratedCertificate.id))


@pytest.mark.parametrize("issued,age,salary", [
    ("2026-11-01", "45", "3044000"), ("2026-11-02", "46", "3044000"),
    ("2027-01-01", "46", "4500000"), ("2025-12-31", "45", ""),
])
def test_age_and_salary_follow_document_date(dossier_case, issued, age, salary):
    client, _, _, company, employee, _ = dossier_case
    fields = suggestion(client, company, employee, issued).json()["fields"]
    assert fields["contract_worker_age"] == age
    assert fields["salary"] == salary


def test_missing_dossier_data_stays_empty_without_creating_a_profile(web_case):
    _, db, _, company, employee, _ = web_case
    employee.contract_type = "No especificado"
    employee.payment_frequency = "No especificado"
    payload = certificate_dossier_data(db, company, employee, date(2026, 11, 2))
    for name in ("contract_worker_age", "contract_worker_gender", "contract_worker_nationality", "work_schedule", "job_functions", "workplace", "contract_modality", "payment_frequency"):
        assert payload["fields"][name] == ""
        assert name in payload["missing_fields"]
        assert name not in payload["sources"]
    assert not db.scalar(select(EmployeeComplianceProfile.id))


def test_foreign_dossiers_and_company_mismatches_are_denied(dossier_case):
    client, _, _, company, employee, other = dossier_case
    for company_id, employee_id in ((company.id, other.id), (other.company_id, other.id), (company.id, 999999)):
        response = client.get("/api/certificates/autofill", params={"company_id": company_id, "employee_id": employee_id})
        assert response.status_code in {403, 404}
        assert other.full_name not in response.text


def test_company_viewer_cannot_fetch_certificate_personal_data(dossier_case):
    client, db, box, company, employee, _ = dossier_case
    box["user"].role = "empresa"
    box["user"].company_id = company.id
    db.commit()
    assert suggestion(client, company, employee).status_code == 403


def test_complete_generation_is_read_only_and_preserves_manual_document_values(dossier_case):
    client, db, _, company, employee, _ = dossier_case
    data = contract_data(client, company, employee)
    data.update(employee_name="Nombre para este contrato", employee_document="CI-documento", salary="3800000", position="Cargo acordado")
    response = client.post("/app/certificates", data=data)
    assert response.status_code == 200, response.text
    body = response.json()["body"]
    assert "COMPLETAR" not in body.upper()
    assert "Nombre para este contrato" in body and "CI-documento" in body
    assert "3.800.000" in body and "Cargo acordado" in body
    assert "Auxiliar administrativo" in body
    assert response.json()["missing_fields"] == {}
    assert not db.scalar(select(GeneratedCertificate.id))
    db.refresh(employee)
    assert employee.full_name == "Persona sintética" and employee.position == "COBRADOR"
    assert employee.base_salary == 4_500_000


def test_legitimate_job_function_can_say_completar_without_being_a_placeholder(dossier_case):
    client, _, _, company, employee, _ = dossier_case
    data = contract_data(client, company, employee)
    data["job_functions"] = "Completar planillas de cobranzas y archivar recibos."
    response = client.post("/app/certificates", data=data)
    assert response.status_code == 200
    assert data["job_functions"] in response.json()["body"]


@pytest.mark.parametrize("intent", ["generate_contract", "save", "approve", "signed", "pdf", "docx"])
def test_missing_critical_data_cannot_generate_or_emit_a_contract(dossier_case, intent):
    client, db, _, company, employee, _ = dossier_case
    data = contract_data(client, company, employee)
    data.update(contract_worker_civil_status="", intent=intent, contract_signature_acknowledged="on")
    response = client.post("/app/certificates", data=data, follow_redirects=False, headers={"Accept": "application/json"})
    assert response.status_code == 400
    assert "Estado civil" in response.json()["detail"]
    assert not db.scalar(select(GeneratedCertificate.id))


def test_incomplete_preview_remains_available_but_lists_missing_fields(dossier_case):
    client, _, _, company, employee, _ = dossier_case
    data = contract_data(client, company, employee)
    data.update(job_functions="", contract_worker_civil_status="", intent="preview")
    response = client.post("/app/certificates", data=data)
    assert response.status_code == 200
    assert response.json()["missing_fields"]["job_functions"] == "Funciones y tareas"
    assert response.json()["missing_fields"]["contract_worker_civil_status"] == "Estado civil"


@pytest.mark.parametrize("name", ["employee_name", "employee_document", "employee_address", "position", "admission_date", "salary"])
def test_clearing_a_required_suggestion_does_not_silently_restore_the_dossier(dossier_case, name):
    client, _, _, company, employee, _ = dossier_case
    data = contract_data(client, company, employee)
    data[name] = "0" if name == "salary" else ""
    response = client.post("/app/certificates", data=data, headers={"Accept": "application/json"})
    assert response.status_code == 400, response.text
    assert "Faltan datos obligatorios" in response.json()["detail"]


def test_saved_values_survive_edits_and_word_pdf_export(dossier_case):
    client, db, _, company, employee, _ = dossier_case
    data = contract_data(client, company, employee)
    data.update(intent="approve", employee_name="Nombre contractual", employee_address="Dirección contractual", salary="3800000")
    response = client.post("/app/certificates", data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    item_id = int(re.search(r"created=(\d+)", response.headers["location"]).group(1))
    saved = db.get(GeneratedCertificate, item_id)
    assert saved.employee_name_snapshot == "Nombre contractual" and saved.salary_snapshot == 3_800_000
    metadata = decode_metadata(saved.observations)
    assert metadata["employee_address"] == "Dirección contractual"
    assert "position" in metadata["autofill_sources"] and "salary" not in metadata["autofill_sources"]
    original_body = saved.body
    employee.position = "Cambio posterior en legajo"
    employee.full_name = "Nombre posterior"
    employee.base_salary = 6_000_000
    db.commit()
    page = client.get(f"/app/certificates?edit_id={item_id}")
    assert page.status_code == 200
    assert 'data-editing-contract="true"' in page.text
    assert 'value="Nombre contractual"' in page.text and 'value="3800000"' in page.text
    assert 'value="COBRADOR"' in page.text
    word = client.get(f"/app/certificates/{item_id}/download.docx")
    pdf = client.get(f"/app/certificates/{item_id}/download.pdf")
    assert word.status_code == pdf.status_code == 200
    word_text = "\n".join(p.text for p in Document(io.BytesIO(word.content)).paragraphs)
    pdf_text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf.content)).pages)
    for text in (word_text, pdf_text):
        assert "Nombre contractual" in text and "Dirección contractual" in text
        assert "3.800.000" in text and "COMPLETAR" not in text.upper()
        assert "Nombre posterior" not in text
    db.refresh(saved)
    assert saved.body == original_body


@pytest.mark.parametrize("changed", [{"contract_text": "Texto [COMPLETAR]"}, {"contract_text": "Texto revisado", "contract_text_stale": "1"}])
def test_placeholder_or_stale_custom_text_cannot_be_approved(dossier_case, changed):
    client, _, _, company, employee, _ = dossier_case
    data = {**contract_data(client, company, employee), "intent": "approve", **changed}
    assert client.post("/app/certificates", data=data).status_code == 400


def test_certificates_share_editable_identity_and_server_preview(dossier_case):
    client, db, _, company, employee, _ = dossier_case
    data = contract_data(client, company, employee)
    data.update(document_type="constancia", intent="preview", employee_name="Nombre corregido solo en documento")
    response = client.post("/app/certificates", data=data)
    assert response.status_code == 200
    assert "Nombre corregido solo en documento" in response.json()["body"]
    db.refresh(employee)
    assert employee.full_name == "Persona sintética"


def test_server_render_bootstrap_escapes_personal_text(dossier_case):
    client, db, _, company, employee, _ = dossier_case
    employee.full_name = "Persona </script><script>alert('x')</script>"
    db.commit()
    page = client.get("/app/certificates", params={"company_id": company.id, "employee_id": employee.id, "document_type": "contrato_trabajo"})
    assert page.status_code == 200
    match = re.search(r'id="certificateAutofillData">(.*?)</script>', page.text, re.S)
    assert json.loads(match.group(1))["fields"]["employee_name"] == employee.full_name
    assert "<script>alert('x')</script>" not in page.text


def test_contract_screen_loads_progressive_jinja_assets_without_react(dossier_case):
    client, _, _, company, employee, _ = dossier_case
    response = client.get("/app/certificates", params={
        "company_id": company.id, "employee_id": employee.id, "document_type": "contrato_trabajo"
    })
    assert response.status_code == 200
    assert 'data-contract-enhance="progressive"' in response.text
    assert "contract-simplified.css" in response.text
    assert "contract-simplified.js" in response.text
    assert 'id="certificatePreview"' in response.text
    assert 'id="certificateForm"' in response.text


def test_progressive_contract_rejects_unconfirmed_suggestions_without_writes(dossier_case):
    client, db, _, company, employee, _ = dossier_case
    data = contract_data(client, company, employee)
    data.update(intent="approve", contract_simplified_submission="1")
    response = client.post("/app/certificates", data=data, headers={"Accept": "application/json"})
    assert response.status_code == 400, response.text
    assert "Confirmá expresamente" in response.json()["detail"]
    assert not db.scalar(select(GeneratedCertificate.id))


@pytest.mark.parametrize("missing", [
    "contract_confirm_payment_frequency",
    "contract_confirm_weekly_rest",
    "contract_confirm_payment_method",
])
def test_progressive_contract_requires_each_explicit_confirmation(dossier_case, missing):
    client, db, _, company, employee, _ = dossier_case
    data = contract_data(client, company, employee)
    data.update(intent="approve", contract_simplified_submission="1",
                contract_confirm_payment_frequency="on",
                contract_confirm_weekly_rest="on",
                contract_confirm_payment_method="on")
    data.pop(missing)
    response = client.post("/app/certificates", data=data)
    assert response.status_code == 400, response.text
    assert not db.scalar(select(GeneratedCertificate.id))


def test_progressive_contract_preview_is_read_only_and_confirmed_approval_succeeds(dossier_case):
    client, db, _, company, employee, _ = dossier_case
    data = contract_data(client, company, employee)
    data.update(contract_simplified_submission="1")
    preview = client.post("/app/certificates", data={**data, "intent": "preview"})
    assert preview.status_code == 200, preview.text
    assert not db.scalar(select(GeneratedCertificate.id))
    data.update(intent="approve", contract_confirm_payment_frequency="on",
                contract_confirm_weekly_rest="on", contract_confirm_payment_method="on")
    response = client.post("/app/certificates", data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    item = db.scalar(select(GeneratedCertificate).where(GeneratedCertificate.document_type == "contrato_trabajo"))
    assert item is not None and item.status == "Aprobado"


def test_progressive_contract_stale_text_still_blocks_approval(dossier_case):
    client, db, _, company, employee, _ = dossier_case
    data = contract_data(client, company, employee)
    data.update(intent="approve", contract_simplified_submission="1",
                contract_confirm_payment_frequency="on", contract_confirm_weekly_rest="on",
                contract_confirm_payment_method="on", contract_text="Texto manual",
                contract_text_stale="1")
    response = client.post("/app/certificates", data=data)
    assert response.status_code == 400, response.text
    assert not db.scalar(select(GeneratedCertificate.id))
