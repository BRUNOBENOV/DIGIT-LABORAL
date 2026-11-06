"""Regression coverage for non-destructive employee archive and linked-record inspection."""
from bs4 import BeautifulSoup
from sqlalchemy import func, select

from app.models import AIInteraction, CalculationRecord, Employee, GeneratedCertificate
from tests.test_employee_deletion import deletion_case
from tests.test_labor_suite import token


def add_references(db, company, employee):
    calc = CalculationRecord(company_id=company.id, employee_id=employee.id,
                             calculation_type="salary", reference_period="2026-10",
                             status="Aprobado", amount=3500000)
    cert = GeneratedCertificate(company_id=company.id, employee_id=employee.id,
                                document_type="constancia", title="Constancia de prueba",
                                company_name_snapshot=company.legal_name, body="Texto de prueba")
    interaction = AIInteraction(studio_id=company.studio_id, company_id=company.id,
                                employee_id=employee.id, purpose="Consulta laboral",
                                user_instruction="Revisión de cálculo <script>alert(1)</script>")
    db.add_all([calc, cert, interaction])
    db.commit()
    return calc, cert, interaction


def test_blocked_delete_can_inspect_records_and_archive_safely(deletion_case):
    client, db, _, company, employee, _ = deletion_case
    calc, cert, interaction = add_references(db, company, employee)
    employee_id = employee.id
    blocked = client.get(f"/app/employees/{employee_id}/permanent-delete")
    assert blocked.status_code == 200
    assert 'Ver registros vinculados' in blocked.text
    assert 'Archivar sin eliminar datos' in blocked.text
    assert BeautifulSoup(blocked.text, "html.parser").select_one('form[action$="/permanent-delete"]') is None

    overview = client.get(f"/app/employees/{employee_id}/linked-records")
    assert overview.status_code == 200
    assert overview.headers["cache-control"] == "no-store"
    for category in ("calculation_records", "generated_certificates", "ai_interactions"):
        assert f"category={category}" in overview.text
    assert f"/app/reports/liquidaciones-salarios/{calc.id}" in overview.text
    assert f"/app/certificates/{cert.id}/print" in overview.text
    assert "Consulta laboral" in overview.text
    assert "&lt;script&gt;" in overview.text
    assert "<script>alert(1)</script>" not in overview.text

    response = client.post(f"/app/employees/{employee_id}/archive",
                           data={"csrf_token": token(client)}, follow_redirects=False)
    assert response.status_code == 303
    db.expire_all()
    archived = db.get(Employee, employee_id)
    assert archived.status == "Archivado"
    assert db.get(CalculationRecord, calc.id) is not None
    assert db.get(GeneratedCertificate, cert.id) is not None
    assert db.get(AIInteraction, interaction.id) is not None
    assert client.get(f"/app/employees/{employee_id}/linked-records").status_code == 200

    response = client.post(f"/app/employees/{employee_id}/restore",
                           data={"csrf_token": token(client)}, follow_redirects=False)
    assert response.status_code == 303
    db.expire_all()
    assert db.get(Employee, employee_id).status == "Activo"


def test_linked_record_category_pagination_is_bounded(deletion_case):
    client, db, _, company, employee, _ = deletion_case
    db.add_all([
        CalculationRecord(company_id=company.id, employee_id=employee.id,
                          calculation_type="notice", status="Borrador", amount=n)
        for n in range(29)
    ])
    db.commit()
    root = f"/app/employees/{employee.id}/linked-records?category=calculation_records"
    first = client.get(root + "&page=1")
    second = client.get(root + "&page=2")
    assert first.status_code == second.status_code == 200
    assert len(BeautifulSoup(first.text, "html.parser").select(".linked-row")) == 25
    assert len(BeautifulSoup(second.text, "html.parser").select(".linked-row")) == 4
    assert "Página 1 de 2" in first.text
    assert "Página 2 de 2" in second.text


def test_linked_record_access_is_studio_scoped_and_read_only(deletion_case):
    client, db, box, company, employee, other = deletion_case
    add_references(db, company, employee)
    before = db.scalar(select(func.count(CalculationRecord.id)).where(CalculationRecord.employee_id == employee.id))
    target = f"/app/employees/{employee.id}/linked-records"
    assert client.get(f"/app/employees/{other.id}/linked-records").status_code == 404
    assert client.get(target + "?category=does_not_exist").status_code == 404
    assert client.get(target + "?category=employee_events").status_code == 404

    box["user"].role = "auxiliar"
    db.commit()
    assert client.get(target).status_code == 403
    box["user"].role = "contador"
    db.commit()
    assert client.get(target).status_code == 200
    after = db.scalar(select(func.count(CalculationRecord.id)).where(CalculationRecord.employee_id == employee.id))
    assert before == after
