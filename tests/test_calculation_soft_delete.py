"""Eliminación lógica auditable y reconciliación histórica: pruebas aisladas."""
from sqlalchemy import select

from app.models import AuditLog, CalculationRecord, IntegrationBatch
from tests.test_salary_rectification import _save_salary, _saved
from tests.test_labor_suite import token, web_case


def test_accountant_can_delete_salary_without_erasing_evidence(web_case):
    client, db, _, company, employee, _ = web_case
    assert _save_salary(client, company, employee).status_code == 303
    item = _saved(db, employee)[0]
    item.status = "Aprobado"
    db.commit()
    original_json, amount = item.result_json, item.amount

    uri = f"/app/liquidaciones?tipo=salary&company_id={company.id}&employee_id={employee.id}"
    page = client.get(uri)
    assert f'/app/calculations/{item.id}/delete' in page.text
    csrf = token(client, uri)
    no_reason = client.post(f"/app/calculations/{item.id}/delete", data={
        "csrf_token": csrf, "reason": "mal", "return_to": "trace",
    })
    assert no_reason.status_code == 422
    assert _saved(db, employee)[0].status == "Aprobado"

    done = client.post(f"/app/calculations/{item.id}/delete", data={
        "csrf_token": csrf, "reason": "Carga duplicada verificada en el legajo", "return_to": "trace",
    }, follow_redirects=False)
    assert done.status_code == 303
    db.expire_all()
    deleted = db.get(CalculationRecord, item.id)
    assert deleted.status == "Anulado"
    assert deleted.result_json == original_json
    assert deleted.amount == amount
    log = db.scalar(select(AuditLog).where(AuditLog.action == "eliminar", AuditLog.entity == "calculo", AuditLog.entity_id == str(item.id)))
    assert log is not None
    assert "duplicada" in log.detail.lower()

    page = client.get(uri)
    assert f"/app/reports/liquidaciones-salarios/{item.id}" not in page.text
    history = client.get(uri + "&deleted_all=1")
    assert history.status_code == 200 and "Eliminado" in history.text
    assert f"/app/reports/liquidaciones-salarios/{item.id}" in history.text
    live_report = client.get("/app/reports/liquidaciones-salarios")
    assert f"DL-LS-{item.id:06d}" not in live_report.text
    deleted_report = client.get("/app/reports/liquidaciones-salarios?status=Anulado")
    assert deleted_report.status_code == 200 and "Eliminado" in deleted_report.text


def test_submitted_salary_cannot_be_deleted_without_resolving_external_link(web_case):
    client, db, _, company, employee, _ = web_case
    assert _save_salary(client, company, employee).status_code == 303
    item = _saved(db, employee)[0]
    db.add(IntegrationBatch(
        studio_id=company.studio_id,
        company_id=company.id, calculation_record_id=item.id,
        authority="REOP", batch_type="salario", period="2026-10",
        status="Presentado", external_reference="TEST-EXTERNAL-REFERENCE",
    ))
    db.commit()
    response = client.post(f"/app/calculations/{item.id}/delete", data={
        "csrf_token": token(client, "/app/liquidaciones?tipo=salary"),
        "reason": "Error a corregir en presentación", "return_to": "trace",
    })
    assert response.status_code == 409
    assert _saved(db, employee)[0].status != "Anulado"


def test_historical_import_dashboard_uses_tenant_audit_not_hardcoded_counts(web_case):
    client, db, box, company, employee, other = web_case
    initial = client.get("/app/import/historical-review")
    assert initial.status_code == 200
    assert "No se encontró una auditoría" in initial.text
    db.add_all([
        AuditLog(
            studio_id=box["user"].studio_id, user_email=box["user"].email,
            action="importar", entity="importacion_historica_mov",
            detail="MOV SHA256=source · 100 antecedentes incorporados; 1 omitidos por existir; 738 rechazados; 6 conflictos; 40 advertencias.",
        ),
        AuditLog(
            studio_id=box["user"].studio_id, user_email=box["user"].email,
            action="importar", entity="importacion_historica_liq",
            detail="LSLIQ SHA256=source · 200 antecedentes vinculados; 2 ya existentes, 87 no vinculados, 4 conflictos, 8265 con advertencias.",
        ),
        AuditLog(
            studio_id=other.company.studio_id if getattr(other, "company", None) else 999999,
            user_email="other@example.invalid", action="importar",
            entity="importacion_historica_liq",
            detail="LSLIQ SHA256=another · 999999 antecedentes vinculados; 0 ya existentes, 0 no vinculados, 0 conflictos, 0 con advertencias.",
        ),
    ])
    db.commit()
    page = client.get("/app/import/historical-review")
    assert page.status_code == 200
    assert "738" in page.text and "87" in page.text
    assert "8265" in page.text and "999999" not in page.text
