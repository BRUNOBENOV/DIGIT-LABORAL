"""Integración mensual de novedades: evidencia, no deducciones presuntas."""
from datetime import date
import json

from sqlalchemy import select

from app.models import CalculationRecord, LaborOperation, Vacation
from app.salary_novelties import salary_novelties
from tests.test_labor_suite import web_case, salary, token  # noqa: F401


def add_novelty(db, company, employee, subtype, start, end, treatment="review",
                status="Aprobado", quantity=None):
    op = LaborOperation(
        company_id=company.id, employee_id=employee.id,
        operation_type="discipline", title=f"Registro {subtype}",
        effective_date=start, end_date=end, status=status,
        payload_json=json.dumps({
            "subtype": subtype, "pay_treatment": treatment, "quantity": quantity,
            "reason": "Prueba con respaldo", "authorized_by": "RRHH",
        }),
    )
    db.add(op)
    db.commit()
    return op


def test_approved_unpaid_absence_is_proposed_without_inventing_ordinary_hours(web_case):
    client, db, _, company, employee, _ = web_case
    add_novelty(db, company, employee, "Suspensión", date(2026, 9, 14),
                date(2026, 9, 15), "unpaid")
    proposal = salary_novelties(db, company.id, employee.id, "2026-09")
    assert proposal["unpaid_days"] == 2
    assert proposal["suggested_paid_days"] == 28
    assert proposal["can_apply_paid_days"]
    assert proposal["observed_worked_days"] == 0
    assert proposal["observed_ordinary_hours"] == "0"
    response = client.get("/api/liquidaciones/novedades-salariales",
                          params={"company_id": company.id, "employee_id": employee.id, "period": "2026-09"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["fingerprint"] == proposal["fingerprint"]


def test_leave_reposo_and_vacations_require_review_without_double_counting(web_case):
    _, db, _, company, employee, _ = web_case
    add_novelty(db, company, employee, "Permiso", date(2026, 9, 12),
                date(2026, 9, 12), "review")
    add_novelty(db, company, employee, "Reposo", date(2026, 9, 13),
                date(2026, 9, 14), "ips")
    add_novelty(db, company, employee, "Suspensión", date(2026, 9, 15),
                date(2026, 9, 15), "unpaid")
    db.add(Vacation(employee_id=employee.id, period_year=2026,
                    entitled_days=12, used_days=3, status="Completada",
                    start_date=date(2026, 9, 14), end_date=date(2026, 9, 16)))
    db.commit()
    proposal = salary_novelties(db, company.id, employee.id, "2026-09")
    assert proposal["paid_leave_days"] == 3
    assert proposal["unpaid_days"] == 0  # La fecha conflictiva se excluye del descuento.
    assert not proposal["can_apply_paid_days"]
    assert proposal["requires_review"]
    assert any("a la vez" in note for note in proposal["warnings"])


def test_registered_suspension_or_partial_permission_never_deducts_salary(web_case):
    _, db, _, company, employee, _ = web_case
    add_novelty(db, company, employee, "Suspensión", date(2026, 9, 1),
                date(2026, 9, 2), "unpaid", status="Registrado")
    add_novelty(db, company, employee, "Permiso", date(2026, 9, 4),
                date(2026, 9, 4), "unpaid", quantity=2)
    proposal = salary_novelties(db, company.id, employee.id, "2026-09")
    assert proposal["unpaid_days"] == 0
    assert proposal["suggested_paid_days"] is None
    assert proposal["requires_review"]


def test_stale_novelty_snapshot_rejected_and_valid_monthly_salary_saved(web_case):
    client, db, _, company, employee, _ = web_case
    op = add_novelty(db, company, employee, "Suspensión",
                     date(2026, 9, 14), date(2026, 9, 15), "unpaid")
    summary = salary_novelties(db, company.id, employee.id, "2026-09")
    data = {
        **salary(month="2026-09", days_paid="28"),
        "csrf_token": token(client), "company_id": str(company.id),
        "employee_id": str(employee.id), "novelties_applied": "on",
        "novelties_fingerprint": summary["fingerprint"],
    }
    changed = dict(data)
    op.status = "Anulado"
    db.commit()
    stale = client.post("/app/liquidaciones/guardar", data=changed, follow_redirects=False)
    assert stale.status_code == 422
    assert not db.scalars(select(CalculationRecord).where(
        CalculationRecord.calculation_type == "suite_salary")).all()
    op.status = "Aprobado"
    db.commit()
    proposal = salary_novelties(db, company.id, employee.id, "2026-09")
    data["novelties_fingerprint"] = proposal["fingerprint"]
    valid = client.post("/app/liquidaciones/guardar", data=data, follow_redirects=False)
    assert valid.status_code == 303, valid.text[:300]
    saved = db.scalar(select(CalculationRecord).where(
        CalculationRecord.calculation_type == "suite_salary"))
    assert json.loads(saved.input_json)["days_paid"] == "28"
