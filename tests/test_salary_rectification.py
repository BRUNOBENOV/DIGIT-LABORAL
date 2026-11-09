"""Rectificación no destructiva y navegación de trazabilidad de Salarios."""
from __future__ import annotations

import json

from sqlalchemy import select

from app.models import AuditLog, CalculationRecord
from tests.test_labor_suite import salary, token, web_case


def _save_salary(client, company, employee, *, salary_value="3500000", **extras):
    csrf = token(client, f"/app/liquidaciones?tipo=salary&company_id={company.id}&employee_id={employee.id}")
    data = salary(
        company_id=str(company.id), employee_id=str(employee.id), csrf_token=csrf,
        month="2026-10", salary=salary_value, days_paid="30",
        days_worked="22", hours_worked="176",
        period_start="2026-10-01", period_end="2026-10-31", **extras,
    )
    response = client.post("/app/liquidaciones/guardar", data=data, follow_redirects=False)
    return response


def _saved(db, employee):
    db.expire_all()
    return list(db.scalars(select(CalculationRecord).where(
        CalculationRecord.employee_id == employee.id,
        CalculationRecord.calculation_type == "suite_salary",
    ).order_by(CalculationRecord.id.asc())))


def test_rectification_creates_linked_draft_without_modifying_approved_original(web_case):
    client, db, _, company, employee, *_ = web_case
    first = _save_salary(client, company, employee)
    assert first.status_code == 303
    original = _saved(db, employee)[0]
    original.status = "Aprobado"
    db.commit()
    old_inputs, old_result, old_amount = original.input_json, original.result_json, original.amount

    trace = client.get(f"/app/liquidaciones?tipo=salary&company_id={company.id}&employee_id={employee.id}")
    assert trace.status_code == 200
    assert "Trazabilidad de cálculos" in trace.text
    assert f'/app/liquidaciones/{original.id}/rectificar' in trace.text

    form = client.get(f"/app/liquidaciones/{original.id}/rectificar")
    assert form.status_code == 200
    assert f'value="{original.id}"' in form.text
    assert "Motivo de la corrección" in form.text
    assert "Nueva versión" in form.text or "nueva versión" in form.text

    reason = "Corregí la base remunerativa según recibo firmado"
    second = _save_salary(
        client, company, employee, salary_value="3600000",
        rectifies_record_id=str(original.id), rectification_reason=reason,
    )
    assert second.status_code == 303, second.text[:400]
    records = _saved(db, employee)
    assert len(records) == 2
    assert records[0].id == original.id
    assert records[0].status == "Aprobado"
    assert records[0].input_json == old_inputs
    assert records[0].result_json == old_result
    assert records[0].amount == old_amount
    correction = records[1]
    assert correction.status == "Borrador"
    assert correction.amount != old_amount
    assert json.loads(correction.input_json)["rectifies_record_id"] == str(original.id)
    assert json.loads(correction.input_json)["rectification_reason"] == reason
    assert any("Rectificación del cálculo #" in msg for msg in json.loads(correction.result_json)["notes"])
    assert db.scalar(select(AuditLog).where(
        AuditLog.action == "rectificar", AuditLog.entity_id == str(correction.id)
    )) is not None

    detail = client.get(f"/app/liquidaciones/{correction.id}")
    assert detail.status_code == 200
    assert f"/app/liquidaciones/{original.id}" in detail.text
    assert "Rectificación del cálculo" in detail.text


def test_rectification_requires_reason_and_same_period(web_case):
    client, db, _, company, employee, *_ = web_case
    assert _save_salary(client, company, employee).status_code == 303
    original = _saved(db, employee)[0]

    no_reason = _save_salary(
        client, company, employee,
        rectifies_record_id=str(original.id), rectification_reason="Error",
    )
    assert no_reason.status_code == 422
    assert "motivo de la rectificación" in no_reason.text
    assert len(_saved(db, employee)) == 1

    csrf = token(client, f"/app/liquidaciones?tipo=salary&company_id={company.id}&employee_id={employee.id}")
    changed_period = client.post("/app/liquidaciones/guardar", data=salary(
        company_id=str(company.id), employee_id=str(employee.id), csrf_token=csrf,
        month="2026-11", salary="3600000", days_paid="30",
        rectifies_record_id=str(original.id),
        rectification_reason="Corrección de sueldo documentada",
    ))
    assert changed_period.status_code == 409
    assert len(_saved(db, employee)) == 1


def test_copy_is_independent_and_approved_put_cannot_overwrite(web_case):
    client, db, _, company, employee, *_ = web_case
    assert _save_salary(client, company, employee).status_code == 303
    first = _saved(db, employee)[0]
    assert _save_salary(
        client, company, employee, salary_value="3600000",
        rectifies_record_id=str(first.id),
        rectification_reason="Datos rectificados con respaldo documental",
    ).status_code == 303
    corrected = _saved(db, employee)[1]
    copied = client.get(f"/app/liquidaciones/{corrected.id}/copiar")
    assert copied.status_code == 200
    assert 'name="rectifies_record_id"' not in copied.text

    first.status = "Aprobado"
    db.commit()
    before = first.input_json
    mutated = client.put(f"/api/calculations/{first.id}", json={
        "kind": "salary", "salary": "10", "month": "2026-10",
    }, headers={"x-csrf-token": token(client, f"/app/liquidaciones/{first.id}")})
    assert mutated.status_code == 409
    db.expire_all()
    assert db.get(CalculationRecord, first.id).input_json == before


def test_rectification_approval_links_back_and_history_has_badges(web_case):
    client, db, _, company, employee, *_ = web_case
    assert _save_salary(client, company, employee).status_code == 303
    first = _saved(db, employee)[0]
    first.status = "Aprobado"
    db.commit()
    assert _save_salary(
        client, company, employee, salary_value="3600000",
        rectifies_record_id=str(first.id),
        rectification_reason="Corrección documentada de salario devengado",
    ).status_code == 303
    second = _saved(db, employee)[1]
    approval = client.post(f"/app/calculations/{second.id}/status", data={
        "csrf_token": token(client, f"/app/liquidaciones/{second.id}"),
        "status": "Aprobado",
    }, follow_redirects=False)
    assert approval.status_code == 303, approval.text[:400]
    db.expire_all()
    assert db.get(CalculationRecord, second.id).status == "Aprobado"
    orig = client.get(f"/app/liquidaciones/{first.id}")
    assert orig.status_code == 200
    assert f"Ver versión aprobada #{second.id}" in orig.text
    history = client.get(f"/app/liquidaciones?tipo=salary&company_id={company.id}&employee_id={employee.id}")
    assert "dl-trace-status" in history.text
    assert f"Rectifica #{first.id}" in history.text


def test_rectification_restores_original_month_from_stale_saved_form_snapshot(web_case):
    """A stale saved month must not make the normal rectify-and-save flow fail 409."""
    from bs4 import BeautifulSoup

    client, db, _, company, employee, *_ = web_case
    assert _save_salary(client, company, employee).status_code == 303
    original = _saved(db, employee)[0]
    original.status = "Aprobado"
    saved_snapshot = json.loads(original.input_json)
    saved_snapshot["month"] = "2026-11"  # Historical saved form drifted from approved record.
    original.input_json = json.dumps(saved_snapshot)
    db.commit()

    response = client.get(f"/app/liquidaciones/{original.id}/rectificar")
    assert response.status_code == 200, response.text[:400]
    soup = BeautifulSoup(response.text, "html.parser")
    form = soup.select_one("#labor-form")
    assert form is not None
    assert form.select_one('[name="kind"]')["value"] == "salary"
    assert form.select_one('[name="month"]')["value"] == "2026-10"
    assert form.select_one('[name="company_id"]')["value"] == str(company.id)
    assert form.select_one('[name="employee_id"]')["value"] == str(employee.id)
    locked = form.select_one("[data-rectification-period]")
    assert locked is not None and locked["data-rectification-period"] == "2026-10"
    assert "month.readOnly = true" in response.text

    corrected_month = form.select_one('[name="month"]')["value"]
    result = _save_salary(
        client, company, employee, month=corrected_month,
        salary_value="3600000", rectifies_record_id=str(original.id),
        rectification_reason="Corrección salarial verificada con recibo del mes",
    )
    assert result.status_code == 303, result.text[:400]
    revisions = _saved(db, employee)
    assert len(revisions) == 2
    assert revisions[0].reference_period == revisions[1].reference_period == "2026-10"
    assert revisions[0].status == "Aprobado"
    assert revisions[1].status == "Borrador"


def test_rectification_rejects_an_attempt_to_change_original_month(web_case):
    client, db, _, company, employee, *_ = web_case
    assert _save_salary(client, company, employee).status_code == 303
    original = _saved(db, employee)[0]
    response = _save_salary(
        client, company, employee, month="2026-11", salary_value="3600000",
        rectifies_record_id=str(original.id),
        rectification_reason="Corrección de mes inválido en documento",
    )
    assert response.status_code == 409
    assert len(_saved(db, employee)) == 1
