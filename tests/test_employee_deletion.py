"""Permanent deletion: scoped review, actual removal, references and atomic audit."""
import json
from datetime import date
from urllib.parse import parse_qs, urlsplit
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app import main as core
from app import employee_deletion_routes as routes
from app.employee_deletion import return_url
from app.models import (AuditLog, CalculationRecord, Document, Employee, EmployeeComplianceProfile,
                        EmployeeEvent, EmployeeExit, FinalSettlement, Payroll, PayrollLine, SalaryHistory, User)
from tests.test_labor_suite import token, web_case


@pytest.fixture
def deletion_case(web_case):
    client, db, box, company, employee, other = web_case
    employee.employee_code = 207001
    employee.admission_date = date(1999, 2, 11)
    db.add_all([
        EmployeeComplianceProfile(employee_id=employee.id, nationality="Paraguaya"),
        EmployeeEvent(employee_id=employee.id, event_type="Importación", title="Legajo histórico", detail="Dato sintético"),
        SalaryHistory(employee_id=employee.id, previous_salary=0, new_salary=3500000,
                      effective_from=employee.admission_date, reason="Importación", created_by=box["user"].email),
        EmployeeComplianceProfile(employee_id=other.id, nationality="Otro estudio"),
        EmployeeEvent(employee_id=other.id, title="Registro de otro estudio"),
        SalaryHistory(employee_id=other.id, previous_salary=0, new_salary=3500000,
                      effective_from=other.admission_date, reason="Otro estudio", created_by=box["user"].email),
    ])
    db.commit()
    return web_case


def path(employee):
    return f"/app/employees/{employee.id}/permanent-delete"


def payload(case, employee=None):
    client, _, _, _, target, _ = case
    employee = target if employee is None else employee
    page = client.get(path(employee))
    assert page.status_code == 200, page.text
    html = BeautifulSoup(page.text, "html.parser")
    form = html.select_one('form[action$="/permanent-delete"]')
    assert form is not None
    data = {field["name"]: field.get("value", "") for field in form.select('input[type="hidden"]')}
    code = employee.employee_code if employee.employee_code is not None else f"ID-{employee.id}"
    return dict(data, confirmation=f"ELIMINAR {code}", reason="Registro de prueba", notes="Prueba automatizada")


def exists(case):
    case[1].expire_all()
    return case[1].get(Employee, case[4].id)


@pytest.mark.parametrize("state", ["Activo", "Desvinculado", "Archivado"])
@pytest.mark.parametrize("role", ["administrador", "contador"])
def test_removes_employee_and_own_profile_in_one_audited_transaction(deletion_case, state, role):
    client, db, box, company, employee, other = deletion_case
    box["user"].role = role
    employee.status = state
    db.commit()
    employee_id, other_id = employee.id, other.id
    data = payload(deletion_case)
    data["return_to"] = f"/app/employees?company_id={company.id}&q=persona&page=4&direction=desc"
    response = client.post(path(employee), data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    target = parse_qs(urlsplit(response.headers["location"]).query)
    assert target["q"] == ["persona"] and target["direction"] == ["desc"] and target["deleted"] == ["1"]
    db.expire_all()
    assert db.get(Employee, employee_id) is None and db.get(Employee, other_id) is not None
    for model in (EmployeeEvent, EmployeeComplianceProfile, SalaryHistory):
        assert db.scalar(select(func.count(model.id)).where(model.employee_id == employee_id)) == 0
        assert db.scalar(select(func.count(model.id)).where(model.employee_id == other_id)) == 1
    for model in (EmployeeExit, FinalSettlement):
        assert db.scalar(select(func.count(model.id))) == 0
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "eliminar_definitivamente"))
    recorded = json.loads(audit.detail)
    assert audit.entity_id == str(employee_id) and audit.user_email == box["user"].email
    assert recorded["employee_code"] == 207001 and recorded["previous_status"] == state
    assert sum(item["count"] for item in recorded["removed_profile_records"]) == 3
    assert client.post(f"/app/employees/{employee_id}/permanent-delete", data=data).status_code == 404
    assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "eliminar_definitivamente")) == 1


@pytest.mark.parametrize("status", ["Borrador", "Aprobado", "Anulado"])
def test_calculations_are_preserved_and_block_deletion(deletion_case, status):
    client, db, _, company, employee, _ = deletion_case
    data = payload(deletion_case)
    record = CalculationRecord(company_id=company.id, employee_id=employee.id, calculation_type="salary", status=status, amount=123456)
    db.add(record); db.commit()
    response = client.get(path(employee))
    assert "Cálculos y liquidaciones" in response.text
    assert BeautifulSoup(response.text, "html.parser").select_one('form[action$="/permanent-delete"]') is None
    blocked = client.post(path(employee), data=data)
    assert blocked.status_code == 409 and exists(deletion_case) is not None
    db.refresh(record)
    assert record.status == status and record.amount == 123456 and record.employee_id == employee.id


@pytest.mark.parametrize("kind", ["document", "payroll"])
def test_documents_and_payroll_references_never_get_detached(deletion_case, kind):
    client, db, _, company, employee, _ = deletion_case
    data = payload(deletion_case)
    if kind == "document":
        record = Document(company_id=company.id, employee_id=employee.id, title="Documento sintético",
                          stored_name="synthetic.pdf", original_name="synthetic.pdf", content_bytes=b"synthetic")
    else:
        payroll = Payroll(company_id=company.id, period="2026-10")
        db.add(payroll); db.flush()
        record = PayrollLine(payroll_id=payroll.id, employee_id=employee.id)
    db.add(record); db.commit()
    assert client.post(path(employee), data=data).status_code == 409
    assert exists(deletion_case) is not None
    db.refresh(record)
    assert record.employee_id == employee.id


@pytest.mark.parametrize("changed", ["employee", "profile", "history"])
def test_changed_dossier_requires_a_fresh_review(deletion_case, changed):
    client, db, _, _, employee, _ = deletion_case
    data = payload(deletion_case)
    if changed == "employee":
        employee.full_name = "Nombre actualizado"
    elif changed == "profile":
        db.scalar(select(EmployeeComplianceProfile).where(EmployeeComplianceProfile.employee_id == employee.id)).nationality = "Actualizada"
    else:
        db.scalar(select(SalaryHistory).where(SalaryHistory.employee_id == employee.id)).reason = "Respaldo actualizado"
    db.commit()
    response = client.post(path(employee), data=data)
    assert response.status_code == 409 and "legajo cambió" in response.text
    assert exists(deletion_case) is not None


@pytest.mark.parametrize("changes,expected", [({"token": ""},409), ({"token": "invalid"},409),
    ({"confirmation": "ELIMINAR OTRO"},422), ({"reason": ""},422),
    ({"reason": "Otro motivo", "notes": ""},422), ({"notes": "x"*501},422)])
def test_missing_or_invalid_confirmation_never_deletes(deletion_case, changes, expected):
    client, *_ = deletion_case
    data = payload(deletion_case); data.update(changes)
    assert client.post(path(deletion_case[4]), data=data).status_code == expected
    assert exists(deletion_case) is not None


def test_expired_review_does_not_delete(deletion_case, monkeypatch):
    monkeypatch.setattr("itsdangerous.timed.TimestampSigner.get_timestamp", lambda self: 1000)
    data = payload(deletion_case)
    monkeypatch.setattr("itsdangerous.timed.TimestampSigner.get_timestamp", lambda self: 2000)
    response = deletion_case[0].post(path(deletion_case[4]), data=data)
    assert response.status_code == 409 and exists(deletion_case) is not None


@pytest.mark.parametrize("role", ["auxiliar", "empresa", "abogado"])
def test_other_roles_have_no_delete_action_and_cannot_call_routes(deletion_case, role):
    client, db, box, company, employee, _ = deletion_case
    data = payload(deletion_case)
    box["user"].role = role; box["user"].company_id = company.id
    db.commit()
    assert client.get(path(employee)).status_code == 403
    assert client.post(path(employee), data=data).status_code == 403
    assert exists(deletion_case) is not None


def test_scope_csrf_and_token_identity_are_checked(deletion_case):
    client, db, _, company, employee, other = deletion_case
    data = payload(deletion_case)
    assert client.get(path(other)).status_code == 404
    assert client.post(path(other), data=data).status_code == 404
    missing_csrf = dict(data); missing_csrf.pop("csrf_token")
    assert client.post(path(employee), data=missing_csrf).status_code == 403
    second = Employee(company_id=company.id, employee_code=207002, full_name="Otra persona", document_number="12345678")
    db.add(second); db.commit()
    assert client.post(path(second), data=dict(data, confirmation="ELIMINAR 207002")).status_code == 409
    assert exists(deletion_case) is not None


@pytest.mark.parametrize("failure", ["delete", "audit"])
def test_failure_rolls_back_employee_profile_and_audit(deletion_case, monkeypatch, failure):
    client, db, _, _, employee, _ = deletion_case
    data = payload(deletion_case)
    if failure == "delete":
        original = routes.remove_dossier
        def fail(session, target):
            original(session, target)
            raise IntegrityError("synthetic", {}, Exception("synthetic"))
        monkeypatch.setattr(routes, "remove_dossier", fail)
    else:
        def fail(*args, **kwargs):
            raise IntegrityError("synthetic", {}, Exception("synthetic"))
        monkeypatch.setattr(routes.core, "write_audit", fail)
    response = client.post(path(employee), data=data)
    assert response.status_code == 409 and exists(deletion_case) is not None
    for model in (EmployeeEvent, EmployeeComplianceProfile, SalaryHistory):
        assert db.scalar(select(func.count(model.id)).where(model.employee_id == employee.id)) == 1
    assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "eliminar_definitivamente")) == 0


def test_unknown_physical_fk_still_prevents_orphaning(deletion_case):
    client, db, _, _, employee, _ = deletion_case
    data = payload(deletion_case)
    with db.bind.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE synthetic_external_link (id INTEGER PRIMARY KEY, employee_id INTEGER REFERENCES employees(id))")
        connection.execute(text("INSERT INTO synthetic_external_link (id,employee_id) VALUES (1,:employee)"), {"employee": employee.id})
    response = client.post(path(employee), data=data)
    assert response.status_code == 409 and exists(deletion_case) is not None
    assert db.scalar(select(func.count(EmployeeEvent.id)).where(EmployeeEvent.employee_id == employee.id)) == 1


def test_database_refusing_parent_delete_rolls_back_profile_cleanup(deletion_case):
    client, db, _, _, employee, _ = deletion_case
    data = payload(deletion_case)
    with db.bind.begin() as connection:
        connection.exec_driver_sql("CREATE TRIGGER synthetic_deny_delete BEFORE DELETE ON employees BEGIN SELECT RAISE(IGNORE); END")
    response = client.post(path(employee), data=data)
    assert response.status_code == 409 and exists(deletion_case) is not None
    assert db.scalar(select(func.count(EmployeeEvent.id)).where(EmployeeEvent.employee_id == employee.id)) == 1
    assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "eliminar_definitivamente")) == 0


def test_review_is_bound_to_the_user_who_opened_it(deletion_case):
    client, db, box, company, employee, _ = deletion_case
    data = payload(deletion_case)
    another = User(studio_id=company.studio_id, full_name="Otro contador", email="other-delete-test@example.invalid",
                   password_hash="unused", role="contador")
    db.add(another); db.commit()
    box["user"] = another
    response = client.post(path(employee), data=data)
    assert response.status_code == 409 and exists(deletion_case) is not None


def test_preview_is_read_only_links_are_visible_and_names_are_escaped(deletion_case):
    client, db, _, company, employee, _ = deletion_case
    employee.full_name = '<script>alert("x")</script>'
    db.commit()
    response = client.get(path(employee))
    assert response.headers["cache-control"] == "no-store"
    assert '&lt;script&gt;' in response.text and exists(deletion_case) is not None
    for url in (f"/app/employees?company_id={company.id}", f"/app/employees/{employee.id}"):
        page = BeautifulSoup(client.get(url).text, "html.parser")
        assert page.select_one(f'a[href^="{path(employee)}"]') is not None


@pytest.mark.parametrize("url", ["https://example.invalid", "//example.invalid/app/employees", "/app/documents", "/app/employees\\evil"])
def test_return_url_cannot_redirect_outside_employee_list(url):
    assert return_url(url, 7) == "/app/employees?company_id=7"
