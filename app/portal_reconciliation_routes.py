"""Read-only reconciliation of an opened IPS planilla against saved Digit salaries."""
from __future__ import annotations

import json
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import main as core
from .models import CalculationRecord, Company, Employee, Payroll, PayrollLine, SalaryImportDetail, User
from .portal_reconciliation import SnapshotError, digits, validate_snapshot
from .reop_assistant import REOP_ASSISTANT_ID
from .salary_data import APPROVED, object_json, salary_query, select_salary_versions

router = APIRouter()
PATH = "/app/compliance/portal-reconciliation"
Operator = Annotated[User, Depends(core.require_roles("administrador", "contador"))]
Database = Annotated[Session, Depends(core.get_db)]


def _company(db: Session, user: User, company_id: int) -> Company:
    return core.company_allowed(db, user, company_id)


def _normalized_expr():
    return func.replace(
        func.replace(func.replace(func.replace(Employee.document_number, ".", ""), "-", ""), " ", ""), "/", ""
    )


@router.get(PATH, response_class=HTMLResponse)
def portal_reconciliation_page(
    request: Request, company_id: int | None = None, period: str = "",
    user: Operator = None, db: Database = None,
):
    ids = core.company_ids_for_user(db, user)
    options = list(db.scalars(
        select(Company).where(
            Company.id.in_(ids), Company.status != "Archivada"
        ).order_by(Company.legal_name)
    )) if ids else []
    company = _company(db, user, company_id) if company_id is not None else None
    from .portal_reconciliation import PERIOD
    if period and not PERIOD.fullmatch(period):
        raise HTTPException(422, "El período debe tener el formato AAAA-MM.")
    return core.render(
        request, "portal_reconciliation.html", db, user,
        companies=options, selected_company=company, period=period,
        assistant_id=REOP_ASSISTANT_ID,
    )


@router.post(PATH + "/preview")
async def portal_reconciliation_preview(
    request: Request, user: Operator = None, db: Database = None,
):
    try:
        payload = await request.json()
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(400, "No se pudo leer la planilla.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(422, "Se esperaba una planilla estructurada.")
    try:
        company_id = int(payload.get("company_id"))
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Seleccioná una empresa.") from exc
    company = _company(db, user, company_id)
    period = str(payload.get("period") or "")
    try:
        items = validate_snapshot(payload.get("snapshot"), company.ips_employer_number, period)
    except SnapshotError as exc:
        raise HTTPException(422, str(exc)) from exc

    docs = {row["document"] for row in items}
    scoped = list(db.scalars(select(Employee).where(
        Employee.company_id.in_(core.company_ids_for_user(db, user)),
        _normalized_expr().in_(docs),
    ).order_by(Employee.id)))
    related: dict[str, list[Employee]] = {}
    for employee in scoped:
        related.setdefault(digits(employee.document_number), []).append(employee)
    selected_ids = [employee.id for employee in scoped if employee.company_id == company.id]

    latest = select_salary_versions(db.scalars(
        salary_query(company.id, period)
    ).all())
    payroll = db.scalar(select(Payroll).where(Payroll.company_id == company.id, Payroll.period == period))
    payroll_lines = {x.employee_id: x for x in db.scalars(
        select(PayrollLine).where(
            PayrollLine.payroll_id == payroll.id, PayrollLine.employee_id.in_(selected_ids)
        )
    )} if payroll and selected_ids else {}
    approved_ids = [item.id for eid, item in latest.items() if eid in selected_ids and item.status in APPROVED]
    annexes = {x.calculation_record_id: x for x in db.scalars(
        select(SalaryImportDetail).where(SalaryImportDetail.calculation_record_id.in_(approved_ids))
    )} if approved_ids else {}

    output, counts = [], {"same_company": 0, "prior_company": 0, "not_found": 0, "approved": 0, "pending": 0}
    for row in items:
        matches = related.get(row["document"], [])
        current = next((x for x in matches if x.company_id == company.id), None)
        elsewhere = [x for x in matches if x.company_id != company.id]
        record = latest.get(current.id) if current else None
        stored = object_json(record.result_json) if record else {}
        inputs = object_json(record.input_json) if record else {}
        annex = annexes.get(record.id) if record else None
        payroll_line = payroll_lines.get(current.id) if current else None
        # A calculation's .amount is the net amount; never mislabel it as gross.
        gross = stored.get("gross")
        if not isinstance(gross, int) or isinstance(gross, bool) or gross < 0:
            gross = int(payroll_line.gross) if payroll_line else None
        status = record.status if record else (payroll.status if payroll_line and payroll else "Sin liquidación")
        if current: counts["same_company"] += 1
        elif elsewhere: counts["prior_company"] += 1
        else: counts["not_found"] += 1
        if record and record.status in APPROVED: counts["approved"] += 1
        else: counts["pending"] += 1

        attended_days = annex.days_worked if annex else inputs.get("days_worked")
        attended_hours = str(annex.hours_worked) if annex else inputs.get("hours_worked")
        payment = annex.payment_method if annex else inputs.get("payment_method")
        payment_date = annex.payment_date.isoformat() if annex and annex.payment_date else inputs.get("payment_date")
        if current:
            action = {"label": "Abrir legajo en " + company.legal_name, "url": f"/app/employees/{current.id}"}
        elif elsewhere:
            action = {
                "label": "Crear vínculo en " + company.legal_name,
                "url": f"/app/employees/{elsewhere[0].id}/change-company?destination_company_id={company.id}#newEmployer",
            }
        else:
            action = {"label": "Crear funcionario en " + company.legal_name,
                      "url": f"/app/employees?company_id={company.id}"}
        output.append({
            **row, "company_id": company.id, "employee_id": current.id if current else None,
            "other_employers": [{"name": x.company.legal_name, "employee_id": x.id} for x in elsewhere],
            "saved_gross": gross, "salary_status": status,
            "salary_source": "Liquidación guardada Digit" if record else ("Nómina guardada Digit" if payroll_line else "Sin datos"),
            "days_actual": attended_days, "hours_actual": attended_hours,
            "payment_method": payment, "payment_date": payment_date,
            "attendance_source": "Anexo de cálculo aprobado" if annex else ("Cálculo guardado Digit" if record else "Sin soporte"),
            "action": action,
            "missing": [name for name, value in [
                ("Jornadas efectivas", attended_days), ("Horas trabajadas", attended_hours),
                ("Forma de pago", payment), ("Fecha de pago", payment_date),
            ] if value in (None, "")],
        })
    return {
        "company": company.legal_name, "period": period, "count": len(output),
        "patronal_verified_in_digit": True, "counts": counts, "rows": output,
        "notice": "Vista de conciliación en lectura. Los importes IPS son declarados; no prueban pago ni equivalen necesariamente al bruto de Digit. No se guardó ni aprobó ningún salario.",
    }
