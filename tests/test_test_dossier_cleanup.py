"""Safe test dossier cleanup: tenant isolation, signed preflight and all-or-none removal."""
import json
from datetime import date

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import func, select, text

from app.models import (
    AIInteraction, Aguinaldo, AuditLog, CalculationRecord, ComplianceEvent, Document,
    Employee, EmployeeEvent, EmployeeExit, FinalSettlement, GeneratedCertificate,
    IntegrationBatch, IntegrationBatchItem, Payroll, PayrollLine,
)
from tests.test_labor_suite import token, web_case

BASE = "/app/employees/{id}/test-cleanup"


def setup_case(web_case):
    client, db, box, company, employee, other = web_case
    box["user"].role = "administrador"
    employee.full_name = "Persona de ejemplo"
    employee.employee_code = 71
    db.commit()
    return client, db, box, company, employee, other


def dossier(db, company, employee):
    calc = CalculationRecord(company_id=company.id, employee_id=employee.id, calculation_type="aguinaldo",
                             reference_period="2026", amount=0, status="Revisar", source="Calculadora v2.4")
    cert = GeneratedCertificate(company_id=company.id, employee_id=employee.id,
        document_type="certificado_trabajo_a", title="Certificado de Trabajo",
        company_name_snapshot=company.legal_name, employee_name_snapshot=employee.full_name,
        status="Emitido", body="Ejemplo sintético")
    db.add_all([calc, cert])
    db.flush()
    exit_record = EmployeeExit(company_id=company.id, employee_id=employee.id,
        effective_date=date(2026, 10, 30), reason="resignation", initiated_by="Trabajador",
        status="Efectivo", constancia_certificate_id=cert.id)
    db.add(exit_record); db.flush()
    final = FinalSettlement(company_id=company.id, employee_id=employee.id,
        employee_exit_id=exit_record.id, status="Pendiente de Cálculo")
    entries = [
        ComplianceEvent(company_id=company.id, employee_id=employee.id,
            authority=authority, event_type="Salida", event_date=date(2026, 10, 30),
            status="Borrador")
        for authority in ("REOP", "REI")
    ]
    db.add_all([final, *entries, EmployeeEvent(employee_id=employee.id, title="Egreso de ejemplo")])
    db.commit()
    return calc, cert, exit_record, final, entries


def form_data(client, employee):
    url = BASE.format(id=employee.id)
    response = client.get(url)
    assert response.status_code == 200, response.text
    html = BeautifulSoup(response.text, "html.parser")
    form = html.select_one(f'form[action="{url}"]')
    assert form is not None, response.text
    values = {x["name"]: x.get("value","") for x in form.select('input[type="hidden"]')}
    values.update({
        "csrf_token": token(client),
        "reason": "Registros ficticios utilizados únicamente en pruebas automatizadas.",
        "declare_synthetic": "on",
        "declare_no_external_use": "on",
        "backup_saved": "on",
        "confirmation": "DEPURAR 71",
    })
    return values


def test_synthetic_bundle_with_exit_certificate_and_unsubmitted_reop_is_atomic(web_case):
    client, db, box, company, employee, other = setup_case(web_case)
    calc, cert, exit_record, final, events = dossier(db, company, employee)
    data = form_data(client, employee)
    assert client.get(BASE.format(id=employee.id)).text.count("Registros de cumplimiento") == 1

    # A typed statement alone is insufficient: the JSON backup must be exported.
    missing = client.post(BASE.format(id=employee.id), data=data, follow_redirects=False)
    assert missing.status_code == 409
    assert db.get(Employee, employee.id) is not None

    export = client.get(BASE.format(id=employee.id) + "/backup.json")
    assert export.status_code == 200 and export.headers["content-type"].startswith("application/json")
    backup = export.json()
    assert backup["employee"]["id"] == employee.id
    assert len(backup["records"]["compliance_events"]) == 2
    assert backup["fingerprint_sha256"]
    response = client.post(BASE.format(id=employee.id), data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    db.expire_all()
    for model, entity_id in ((Employee, employee.id), (CalculationRecord,calc.id),
                             (GeneratedCertificate,cert.id), (EmployeeExit,exit_record.id),
                             (FinalSettlement,final.id)):
        assert db.get(model, entity_id) is None
    assert db.scalar(select(func.count(ComplianceEvent.id)).where(ComplianceEvent.employee_id == employee.id)) == 0
    assert db.get(Employee, other.id) is not None
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "depurar_legajo_sintetico"))
    assert audit is not None
    log = json.loads(audit.detail)
    assert log["deleted_counts"]["compliance_events"] == 2
    assert log["snapshot_sha256"] == backup["fingerprint_sha256"]


def test_real_name_or_synthetic_company_does_not_allow_purge(web_case):
    client, db, box, company, employee, other = setup_case(web_case)
    employee.full_name = "Trabajador real"
    company.legal_name = "Prueba personal de laboratorio"
    db.commit()
    response = client.get(BASE.format(id=employee.id))
    assert response.status_code == 200
    assert "Depuración bloqueada" in response.text
    assert 'name="confirmation"' not in response.text
    assert client.get(BASE.format(id=employee.id) + "/backup.json").status_code == 409
    assert client.post(BASE.format(id=employee.id), data={"csrf_token": token(client)}).status_code == 409
    assert db.get(Employee, employee.id) is not None


@pytest.mark.parametrize("kind", [
    "submitted", "with_receipt", "in_batch", "paid_settlement",
    "approved_calc", "attachment", "official_payroll",
])
def test_protected_evidence_blocks_everything(web_case, kind):
    client, db, box, company, employee, other = setup_case(web_case)
    calc, cert, exit_record, final, events = dossier(db, company, employee)
    if kind == "submitted":
        events[0].status="Enviado"
        events[0].submitted_at=core_time()
    elif kind == "with_receipt":
        events[0].external_reference="REOP-TEST-123"
    elif kind == "in_batch":
        batch = IntegrationBatch(studio_id=company.studio_id, company_id=company.id,
                                 authority="REOP", batch_type="Salida", status="Generado")
        db.add(batch); db.flush()
        db.add(IntegrationBatchItem(batch_id=batch.id, compliance_event_id=events[0].id))
    elif kind == "paid_settlement":
        final.status="Pagada"; final.payment_amount=100; final.payment_date=date(2026,10,30)
    elif kind == "approved_calc":
        calc.status="Aprobado"
    elif kind == "attachment":
        db.add(Document(company_id=company.id, employee_id=employee.id,
                        title="Archivo", stored_name="e.pdf", original_name="e.pdf"))
    elif kind == "official_payroll":
        payroll=Payroll(company_id=company.id, period="2026-10", status="Cerrado")
        db.add(payroll); db.flush()
        db.add(PayrollLine(payroll_id=payroll.id,employee_id=employee.id, net=1500000))
    db.commit()
    assert "Depuración bloqueada" in client.get(BASE.format(id=employee.id)).text
    assert client.get(BASE.format(id=employee.id)+"/backup.json").status_code == 409
    assert client.post(BASE.format(id=employee.id),data={"csrf_token":token(client)}).status_code == 409
    db.expire_all()
    assert db.get(Employee, employee.id) is not None
    assert db.get(CalculationRecord,calc.id) is not None
    assert db.get(GeneratedCertificate,cert.id) is not None


def core_time():
    from datetime import UTC, datetime
    return datetime.now(UTC)


def test_security_csrf_tampering_and_snapshot_change(web_case):
    client, db, box, company, employee, other = setup_case(web_case)
    calc, *_ = dossier(db, company, employee)
    assert client.get(BASE.format(id=other.id)).status_code == 404
    data = form_data(client, employee)
    assert client.post(BASE.format(id=employee.id), data={k:v for k,v in data.items() if k!="csrf_token"}).status_code == 403
    client.get(BASE.format(id=employee.id)+"/backup.json")
    forged = dict(data, confirmation="DEPURAR OTRO")
    assert client.post(BASE.format(id=employee.id),data=forged).status_code == 422
    no_attestation = dict(data,declare_no_external_use="")
    assert client.post(BASE.format(id=employee.id),data=no_attestation).status_code == 422
    calc.notes = "Se cambió el cálculo"
    db.commit()
    assert client.post(BASE.format(id=employee.id),data=data).status_code == 409
    assert db.get(Employee,employee.id) is not None
    box["user"].role="contador"
    db.commit()
    assert client.get(BASE.format(id=employee.id)).status_code == 403
    assert client.post(BASE.format(id=employee.id),data=data).status_code == 403


def test_unknown_physical_dependency_prevents_purge(web_case):
    client, db, box, company, employee, _ = setup_case(web_case)
    with db.bind.begin() as connection:
        connection.execute(text("CREATE TABLE extra_employee_reference (id INTEGER PRIMARY KEY, employee_id INTEGER REFERENCES employees(id))"))
        connection.execute(text("INSERT INTO extra_employee_reference (id, employee_id) VALUES (9, :employee_id)"),
                           {"employee_id": employee.id})
    page=client.get(BASE.format(id=employee.id))
    assert page.status_code == 200
    assert "Tabla externa extra_employee_reference" in page.text
    assert client.post(BASE.format(id=employee.id),data={"csrf_token":token(client)}).status_code == 409
    assert db.get(Employee,employee.id) is not None
