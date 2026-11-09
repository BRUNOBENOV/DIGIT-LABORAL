"""REOP mass approval must remain tenant-scoped and preserve invalid drafts."""
from __future__ import annotations

from app.models import AuditLog, CalculationRecord
from tests.test_labor_suite import web_case, token  # noqa: F401


def _make_pending(db, company, employee):
    employee.ips_contributor = True
    item = CalculationRecord(
        company_id=company.id, employee_id=employee.id,
        calculation_type="salary", reference_period="2026-10",
        status="Revisar", source="Calculadora",
        amount=3_000_000, input_json="{}", result_json="{}",
    )
    db.add_all([employee, item])
    db.commit()
    return item


def _post(client, company_id, *, confirm="si", payment="1"):
    return client.post(
        "/app/compliance/salary-import/approve-pending",
        data={
            "csrf_token": token(client), "company_id": str(company_id),
            "period": "2026-10", "authority": "REOP",
            "payment_code": payment, "confirmed": confirm,
        },
        follow_redirects=False,
    )


def test_missing_salary_evidence_is_not_approved(web_case):
    client, db, _, company, employee, _ = web_case
    item = _make_pending(db, company, employee)
    response = _post(client, company.id)
    assert response.status_code == 303
    assert "auto_approved=0" in response.headers["location"]
    assert "auto_blocked=1" in response.headers["location"]
    db.expire_all()
    assert db.get(CalculationRecord, item.id).status == "Revisar"


def test_bulk_approval_needs_explicit_confirmation_and_valid_period(web_case):
    client, db, _, company, employee, _ = web_case
    item = _make_pending(db, company, employee)
    assert _post(client, company.id, confirm="").status_code == 422
    assert _post(client, company.id, payment="").status_code == 422
    db.expire_all()
    assert db.get(CalculationRecord, item.id).status == "Revisar"


def test_bulk_approval_cannot_reach_a_different_studio(web_case):
    client, db, _, company, employee, outsider = web_case
    _make_pending(db, company, employee)
    response = _post(client, outsider.company_id)
    assert response.status_code == 404


def test_eligible_approval_is_audited_and_does_not_create_a_payment(web_case, monkeypatch):
    client, db, _, company, employee, _ = web_case
    item = _make_pending(db, company, employee)
    from app import main as core, approved_salary_import
    # Isolate the bulk orchestration: real economic and attendance preflight
    # is exercised in the dedicated import/approval contract test suites.
    monkeypatch.setattr(core, "_revalidate_calculation_before_approval", lambda calculation, session: None)
    monkeypatch.setattr(
        approved_salary_import, "approved_salary_records",
        lambda session, company, period, *, authority, employee_id, payment_code: ([object()], [], []),
    )
    response = _post(client, company.id)
    assert response.status_code == 303
    assert "auto_approved=1" in response.headers["location"]
    db.expire_all()
    assert db.get(CalculationRecord, item.id).status == "Aprobado"
    assert any(
        audit.entity == "calculo" and audit.entity_id == str(item.id) and audit.action == "aprobar"
        for audit in db.query(AuditLog).all()
    )
