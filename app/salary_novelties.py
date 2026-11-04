"""Conciliación conservadora de novedades para la liquidación salarial.

Los registros de movimientos NO equivalen a un control de asistencia completo.
Nunca se deducen reposos, permisos o vacaciones por inferencia: se requiere
clasificación del pago y aprobación. Las horas son las efectivamente registradas.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
import re

from sqlalchemy import or_, select

from .models import CompanyRequest, EmployeeEvent, LaborOperation, Vacation


def _payload(raw):
    try:
        obj = json.loads(raw or "{}")
        return obj if isinstance(obj, dict) else {}
    except (ValueError, TypeError):
        return {}


def _days(start, end, first, last):
    start = max(start, first)
    end = min(end, last)
    if end < start:
        return set()
    return {start + timedelta(days=i) for i in range((end - start).days + 1)}


def salary_novelties(db, company_id: int, employee_id: int, period: str, pay_basis: str = "monthly") -> dict:
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", str(period or "")):
        raise ValueError("Seleccioná un mes válido para consultar las novedades.")
    if pay_basis not in {"monthly", "daily"}:
        raise ValueError("Modalidad salarial inválida.")
    year, month = map(int, period.split("-"))
    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    entries = []
    warnings = []
    paid = set()
    unpaid = set()
    regular = {}
    unresolved = False

    operations = db.scalars(select(LaborOperation).where(
        LaborOperation.company_id == company_id,
        LaborOperation.employee_id == employee_id,
        LaborOperation.operation_type.in_(("discipline", "hours")),
        LaborOperation.effective_date <= last,
        or_(LaborOperation.end_date.is_(None), LaborOperation.end_date >= first),
        LaborOperation.status != "Anulado",
    ).order_by(LaborOperation.effective_date, LaborOperation.id)).all()
    for op in operations:
        data = _payload(op.payload_json)
        when = _days(op.effective_date, op.end_date or op.effective_date, first, last)
        if not when:
            continue
        if op.operation_type == "hours":
            if op.status != "Aprobado":
                unresolved = True
                entries.append({"type": "Horas", "title": op.title, "status": op.status,
                                "days": len(when), "detail": "Jornada pendiente de aprobación", "id": f"operacion:{op.id}"})
                continue
            hrs = Decimal(str(data.get("regular_hours") or "0"))
            if hrs > 0:
                regular[op.effective_date] = regular.get(op.effective_date, Decimal(0)) + hrs
            entries.append({"type": "Horas", "title": op.title, "status": op.status,
                            "days": 1, "detail": f"{hrs} h ordinarias registradas", "id": f"operacion:{op.id}"})
            continue

        subtype = str(data.get("subtype") or "").strip()
        if subtype == "Amonestación":
            entries.append({"type": subtype, "title": op.title, "status": op.status,
                            "days": len(when), "detail": "No genera descuento automático", "id": f"operacion:{op.id}"})
            continue
        if subtype not in {"Permiso", "Suspensión", "Reposo"}:
            unresolved = True
            warnings.append(f"Revisar la clasificación de la novedad #{op.id}.")
            continue
        treatment = str(data.get("pay_treatment") or "review")
        partial_hours = data.get("quantity") not in ("", None, 0, 0.0, "0")
        authorized = op.status == "Aprobado"
        detail = {
            "paid": "Remunerado; no se descuenta",
            "unpaid": "Sin goce de sueldo, sujeto a revisión",
            "ips": "Reposo/subsidio IPS; verificar obligación patronal",
            "review": "Tratamiento salarial pendiente",
        }.get(treatment, "Tratamiento salarial pendiente")
        if not authorized or treatment in {"ips", "review"} or partial_hours:
            unresolved = True
            if partial_hours:
                detail += " · Horas parciales: no convertir a días completos"
        elif treatment == "paid":
            paid.update(when)
        elif treatment == "unpaid":
            unpaid.update(when)
        else:
            unresolved = True
        entries.append({"type": subtype, "title": op.title, "status": op.status,
                        "days": len(when), "detail": detail, "id": f"operacion:{op.id}"})

    vacations = db.scalars(select(Vacation).where(
        Vacation.employee_id == employee_id,
        Vacation.status.in_(("Aprobada", "Completada")),
        Vacation.start_date.is_not(None), Vacation.end_date.is_not(None),
        Vacation.start_date <= last, Vacation.end_date >= first,
    ).order_by(Vacation.start_date, Vacation.id)).all()
    for item in vacations:
        when = _days(item.start_date, item.end_date, first, last)
        paid.update(when)
        entries.append({"type": "Vacaciones", "title": f"Período {item.period_year}",
                        "status": item.status, "days": len(when),
                        "detail": "Descanso remunerado; no equivale a horas trabajadas",
                        "id": f"vacaciones:{item.id}"})

    requests = db.scalars(select(CompanyRequest).where(
        CompanyRequest.company_id == company_id,
        CompanyRequest.employee_id == employee_id,
        CompanyRequest.status == "Aplicada",
        CompanyRequest.start_date.is_not(None), CompanyRequest.end_date.is_not(None),
        CompanyRequest.start_date <= last, CompanyRequest.end_date >= first,
    ).order_by(CompanyRequest.id)).all()
    for item in requests:
        kind = (item.request_type or "").strip().lower()
        if kind in {"permiso/licencia", "permiso", "licencia"}:
            when = _days(item.start_date, item.end_date, first, last)
            unresolved = True  # Las solicitudes antiguas no identifican el tratamiento salarial.
            entries.append({"type": "Permiso/licencia", "title": item.leave_type or "Permiso",
                            "status": item.status, "days": len(when),
                            "detail": "Solicitud aplicada; confirmar remuneración y horas", "id": f"solicitud:{item.id}"})
        elif kind == "vacaciones":
            # El movimiento de la solicitud puede actualizar un registro de Vacation;
            # union por día, sin sumar dos veces el mismo descanso.
            when = _days(item.start_date, item.end_date, first, last)
            paid.update(when)
            entries.append({"type": "Vacaciones", "title": f"Solicitud #{item.id}",
                            "status": item.status, "days": len(when),
                            "detail": "Descanso remunerado, sin doble cómputo", "id": f"solicitud:{item.id}"})

    # Los reposos históricos en línea de tiempo son texto libre, no contienen una
    # duración normalizada fiable: alertar, nunca deducir una jornada de ahí.
    legacy_events = db.scalars(select(EmployeeEvent).where(
        EmployeeEvent.employee_id == employee_id,
        EmployeeEvent.effective_date >= first, EmployeeEvent.effective_date <= last,
        EmployeeEvent.event_type.in_(("Reposo", "Ausencia", "Permiso")),
    )).all()
    for event in legacy_events:
        if event.event_type == "Permiso" and "mediante solicitud #" in (event.title or ""):
            continue  # Ya se consultó la solicitud aplicada.
        unresolved = True
        entries.append({"type": event.event_type, "title": event.title,
                        "status": "Histórico", "days": None,
                        "detail": "Revisar fechas y respaldo; no se descuenta automáticamente",
                        "id": f"evento:{event.id}"})

    conflict = paid & unpaid
    if conflict:
        unresolved = True
        warnings.append(f"{len(conflict)} fecha(s) figuran a la vez como descanso remunerado y ausencia sin goce. Conciliá los registros.")
    effective_unpaid = unpaid - paid
    month31 = monthrange(year, month)[1] == 31 and bool(effective_unpaid)
    if month31:
        warnings.append("Mes de 31 días: revisar personalmente la correspondencia con la base mensual de 30 antes de descontar.")
    if unresolved:
        warnings.append("Hay movimientos sin aprobación, pago definido o fechas completas. No se aplican descuentos sobre ellos.")
    if not regular:
        warnings.append("No hay una asistencia diaria aprobada completa: no se pueden inferir horas ordinarias ni días efectivos.")
    if regular:
        warnings.append("Las horas registradas pueden ser parciales; confirmá que toda la asistencia del período esté cargada.")

    suggested = (30 - len(effective_unpaid)
                 if pay_basis == "monthly" and effective_unpaid and not unresolved and not month31 and not conflict
                 else None)
    if suggested is not None:
        suggested = max(0, suggested)
    items = [{"date": day.isoformat(), "hours": str(value)} for day, value in sorted(regular.items())]
    result = {
        "period": period, "pay_basis": pay_basis, "events": entries,
        "unpaid_days": len(effective_unpaid), "paid_leave_days": len(paid),
        "observed_worked_days": len(regular), "observed_ordinary_hours": str(sum(regular.values(), Decimal(0))),
        "daily_attendance": items, "suggested_paid_days": suggested,
        "can_apply_paid_days": suggested is not None,
        "requires_review": unresolved or bool(conflict) or month31,
        "warnings": warnings,
    }
    result["fingerprint"] = hashlib.sha256(
        json.dumps(result, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return result
