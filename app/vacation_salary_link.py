"""Vinculación de vacaciones pagadas con el mes salarial, sin duplicar ingresos.

La plantilla Excel REOP de 32 columnas no tiene columna de vacaciones.
El vínculo informa períodos y pago real; NUNCA mueve importes entre columnas
ni recalcula bases IPS sin un cálculo salarial aprobado que lo respalde.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
import json
from sqlalchemy import select

from .models import ComplianceEvent, Employee, Vacation


def vacation_links_for_period(db, company_id: int, period: str, employee_ids=None):
    year, month = map(int, period.split("-"))
    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    query = (
        select(Vacation, Employee)
        .join(Employee, Employee.id == Vacation.employee_id)
        .where(
            Employee.company_id == company_id,
            Vacation.start_date.is_not(None),
            Vacation.end_date.is_not(None),
            Vacation.status.in_(("Aprobada", "Completada")),
            Vacation.start_date <= last,
            Vacation.end_date >= first,
        )
        .order_by(Employee.full_name, Vacation.start_date, Vacation.id)
    )
    if employee_ids is not None:
        if not employee_ids:
            return []
        query = query.where(Vacation.employee_id.in_(employee_ids))
    rows = []
    for vac, employee in db.execute(query):
        start, end = max(vac.start_date, first), min(vac.end_date, last)
        calendar_days = (end - start).days + 1
        paid_amount = vac.paid_amount
        rows.append({
            "id": vac.id,
            "employee_id": employee.id,
            "employee_name": employee.full_name,
            "start": vac.start_date,
            "end": vac.end_date,
            "start_in_period": start,
            "end_in_period": end,
            "calendar_days_in_period": calendar_days,
            "paid_amount": paid_amount,
            "payment_date": vac.payment_date,
            "payment_verified": paid_amount is not None and vac.payment_date is not None and paid_amount > 0,
            "status": vac.status,
            "url": f"/app/vacations/{vac.id}",
        })
    return rows


def synchronize_vacation_draft(db, vacation: Vacation, company_id: int) -> bool:
    """Actualiza solo la comunicación REOP en borrador, nunca lo ya validado/presentado."""
    event = db.scalar(select(ComplianceEvent).where(
        ComplianceEvent.company_id == company_id,
        ComplianceEvent.employee_id == vacation.employee_id,
        ComplianceEvent.authority == "REOP",
        ComplianceEvent.event_type == "Vacaciones",
        ComplianceEvent.source_key == f"vacation:{vacation.id}:reop",
        ComplianceEvent.status == "Borrador",
    ))
    if event is None:
        return False
    try:
        payload = json.loads(event.payload_json or "{}")
        if not isinstance(payload, dict):
            payload = {}
    except (TypeError, ValueError):
        payload = {}
    payload.update({
        "vacation_id": vacation.id,
        "period_year": vacation.period_year,
        "end_date": vacation.end_date.isoformat() if vacation.end_date else "",
        "paid_amount": vacation.paid_amount,
        "payment_date": vacation.payment_date.isoformat() if vacation.payment_date else "",
    })
    event.payload_json = json.dumps(payload, ensure_ascii=False)
    return True
