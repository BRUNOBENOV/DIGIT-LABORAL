"""Read-only salary export projection of previously imported historical MOV evidence.

Only use original values or separately documented supplements. An imported MOV
is not itself proof of payment, nor a calculation/receipt. No source mutation.
"""
from __future__ import annotations

from calendar import monthrange
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from .legacy_salary_mov_import import EVENT_TYPE, event_data
from .models import Employee, EmployeeEvent, HistoricalMovExportDetail


def _whole(raw, label: str, errors: list[str], *, required: bool = False):
    if raw in (None, ""):
        if required:
            errors.append(f"falta {label} en MOV")
        return None if required else 0
    try:
        value = Decimal(str(raw))
        if (not value.is_finite() or value < 0
                or value != value.to_integral_value() or value > 2_147_483_647):
            raise ValueError
        return int(value)
    except (InvalidOperation, ValueError, TypeError):
        errors.append(f"{label} de MOV no es un entero monetario válido")
        return None


def _days(raw, label: str, errors: list[str], maximum=31):
    value = _whole(raw, label, errors, required=True)
    if value is None:
        return None
    if value > maximum:
        errors.append(f"{label} supera {maximum}")
        return None
    return value


def mov_events(db: Session, company_id: int, period: str, *, employee_id: int | None = None):
    """Month-scoped, company-scoped source selection, not a union with new salaries."""
    query = select(EmployeeEvent, Employee).join(
        Employee, Employee.id == EmployeeEvent.employee_id
    ).where(
        Employee.company_id == company_id,
        EmployeeEvent.event_type == EVENT_TYPE,
        EmployeeEvent.effective_date == date.fromisoformat(period + "-01"),
    ).order_by(Employee.full_name, EmployeeEvent.id)
    if employee_id is not None:
        query = query.where(Employee.id == employee_id)
    return db.execute(query).all()


def mov_employee_choices(db: Session, company_id: int, period: str, *, authority: str):
    from .approved_salary_import import salary_export_employee_eligible
    if not period or len(period) != 7:
        return []
    rows = mov_events(db, company_id, period)
    choices = {employee.id: employee for _, employee in rows
               if salary_export_employee_eligible(employee, authority)}
    return sorted(choices.values(), key=lambda employee: (employee.full_name, employee.id))


def mov_salary_records(
    db: Session, company, period: str, *, authority: str = "REOP",
    employee_id: int | None = None, payment_code: str = "",
    exclude_employee_ids: set[int] | None = None, allow_empty: bool = False,
):
    """Return (line, employee, detail) for source-verified MOV entries.

    All skipped/ambiguous entries produce a blocking diagnostic. An exporter
    must refuse a file whenever errors are present, not silently omit data.
    """
    from .approved_salary_import import salary_export_employee_eligible

    source = []
    errors = []
    diagnostics = []
    if authority not in {"REOP", "REI"}:
        return [], ["Organismo inválido."], []
    entries = mov_events(db, company.id, period, employee_id=employee_id)
    if exclude_employee_ids:
        entries = [(event, worker) for event, worker in entries
                   if worker.id not in exclude_employee_ids]
    if not entries:
        return [], ([] if allow_empty else
                    ["No hay salarios guardados en esta empresa y período."]), []

    counts = Counter(emp.id for _, emp in entries if salary_export_employee_eligible(emp, authority))
    event_ids = [event.id for event, emp in entries]
    supplements = {
        supplement.event_id: supplement
        for supplement in db.scalars(
            select(HistoricalMovExportDetail).where(
                HistoricalMovExportDetail.event_id.in_(event_ids),
                HistoricalMovExportDetail.company_id == company.id,
            )
        )
    } if event_ids else {}
    month_start = date.fromisoformat(period + "-01")
    month_end = date(month_start.year, month_start.month, monthrange(month_start.year, month_start.month)[1])
    for event, employee in entries:
        # Do not export IPS No (nor inactive employees to the REI).
        if not salary_export_employee_eligible(employee, authority):
            continue
        info = event_data(event.detail) or {}
        raw = info.get("values") or {}
        supplement = supplements.get(event.id)
        issue = []
        context = f"{employee.full_name} (MOV #{event.id})"
        if counts[employee.id] != 1:
            issue.append("hay varios MOV del mismo funcionario y período; identificá la versión correcta")
        if info.get("period") != period or event.effective_date != month_start:
            issue.append("el período del MOV no coincide con el solicitado")
        if not info.get("source_hash") or len(str(info["source_hash"])) != 64:
            issue.append("falta la huella de origen verificable")
        if supplement and supplement.source_hash != info.get("source_hash"):
            issue.append("cambió la huella de origen desde que se documentaron los complementos")
            supplement = None
        if str(info.get("company_code") or "").strip() != str(company.legacy_code or "").strip():
            issue.append("CODEMP no coincide con la empresa de origen")
        if info.get("warnings"):
            issue.append("MOV con advertencias de origen: " + "; ".join(str(x) for x in info["warnings"]))
        currency = str(raw.get("MONEDA") or "").strip().casefold().replace(".", "")
        if currency and currency not in {"gs", "g", "pyg", "₲", "guaranies", "guaraníes"}:
            issue.append("moneda original distinta de guaraníes; no se convierte automáticamente")

        gross = _whole(raw.get("SALARI"), "salario bruto SALARI", issue, required=True)
        # SALARI1 is an independent historical DOS amount, not proof of a
        # net salary. The MTESS salary real / salary payable columns can both
        # hold the gross salary: never subtract IPS to validate SALARI1.
        secondary_salary = _whole(raw.get("SALARI1"), "SALARI1", issue, required=False)
        discount_ips = _whole(raw.get("DESIPS"), "aporte DESIPS", issue, required=True)
        discount_other = _whole(raw.get("DESOTR"), "otros descuentos DESOTR", issue)
        base_current = _whole(raw.get("SALACT"), "salario SALACT", issue)
        for name in ("COMREM", "BONIFI", "HOREXT", "HOR030", "HOR050", "HOR080",
                     "HOR100", "HOR130"):
            value = _whole(raw.get(name), name, issue)
            if value:
                issue.append(f"el componente {name} exige clasificación documental antes de exportar")
        if gross is None or discount_ips is None or discount_other is None:
            expected_net = None
        else:
            expected_net = gross - discount_ips - discount_other
            if expected_net < 0:
                issue.append("los descuentos superan la remuneración original")
            # Keep SALARI1 for documentary comparison; do not reinterpret it
            # as cash actually received or as net pay.
        # Only infer an IPS base when the ORIGINAL current salary and SALARI
        # coincide and the explicitly recorded DESIPS is exactly 9% of it.
        # Otherwise require an independently documented base.
        base = supplement.ips_base if supplement and supplement.ips_base is not None else None
        if base is None and gross is not None and discount_ips is not None and base_current == gross and gross > 0:
            computed = int((Decimal(gross) * Decimal("0.09")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if computed == discount_ips:
                base = gross
        if base is None:
            issue.append("falta base IPS documentada (SALARI no se presume automáticamente base imponible)")
        elif discount_ips is not None:
            expected_ips = int((Decimal(base) * Decimal("0.09")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if expected_ips != discount_ips:
                issue.append("DESIPS no coincide con el 9 % de la base IPS documentada")

        from_raw_days = raw.get("DIATRA")
        days = supplement.days_worked if supplement and supplement.days_worked is not None else _days(
            from_raw_days, "días efectivamente trabajados DIATRA", issue)
        if days is not None and not 0 <= days <= 31:
            issue.append("días trabajados fuera del rango permitido")
        from_raw_hours = raw.get("HORASX")
        # In DOS, HORASX frequently contains a clock time (e.g. 11:54:58)
        # rather than a duration. A clock time is NEVER working hours.
        is_clock_time = isinstance(from_raw_hours, str) and ":" in from_raw_hours
        h = (supplement.hours_worked if supplement and supplement.hours_worked is not None
             else None if is_clock_time else from_raw_hours)
        try:
            hours = Decimal(str(h))
            if not hours.is_finite() or hours <= 0 or hours > 744:
                raise ValueError
        except (InvalidOperation, ValueError, TypeError):
            hours = Decimal(0)
            if authority == "REOP":
                issue.append(
                    "faltan horas ordinarias efectivamente trabajadas: "
                    "HORASX registra una hora de reloj, no horas trabajadas; "
                    "completá las horas con respaldo"
                    if is_clock_time else
                    "faltan horas ordinarias efectivamente trabajadas (completá con respaldo)"
                )
        raw_basis = str(employee.payment_frequency or "").casefold()
        basis = supplement.pay_basis if supplement and supplement.pay_basis else (
            "monthly" if "mensual" in raw_basis else "daily" if "jornal" in raw_basis or "diari" in raw_basis else "")
        days_paid = supplement.days_paid if supplement and supplement.days_paid is not None else None
        if days_paid is None and raw.get("DIATRA1") not in (None, ""):
            days_paid = _days(raw["DIATRA1"], "días remunerados DIATRA1", issue, maximum=31)
        if basis == "monthly" and days_paid is None:
            issue.append("faltan días remunerados DIATRA1 para el mensualizado")
        # If both possible regimes yield exactly the same declared days, the
        # unknown historic modality does not alter these REOP/REI fields.
        # When they differ, explicit documentary classification is needed.
        if basis not in {"monthly", "daily"} and (days is None or days_paid is None or days_paid != days):
            issue.append("confirmá si el salario histórico era mensualizado o jornalero: las jornadas declaradas difieren")
        if days_paid is not None and not 0 <= days_paid <= 31:
            issue.append("días remunerados fuera de rango")
        try:
            dstart = date(month_start.year, month_start.month, int(Decimal(str(raw.get("PAGDEL")))))
            dend = date(month_start.year, month_start.month, int(Decimal(str(raw.get("PAGALX")))))
            if dend < dstart:
                raise ValueError
        except (InvalidOperation, TypeError, ValueError, OverflowError):
            issue.append("PAGDEL/PAGALX no indican un intervalo de fechas calendario válido")
            dstart, dend = month_start, month_end

        if issue:
            errors.extend(f"{context}: {problem}." for problem in issue)
        diagnostics.append({
            "id": event.id, "employee_id": employee.id, "employee": employee.full_name,
            "period": period, "origin": info.get("filename") or "MOV",
            "source_row": info.get("source_row"),
            "warnings": issue, "source_hash": info.get("source_hash") or "",
            "has_supplement": bool(supplement),
            "raw": {name: raw.get(name, "") for name in (
                "SALARI", "SALARI1", "SALACT", "DESIPS", "DESOTR",
                "DIATRA", "DIATRA1", "HORASX", "PAGDEL", "PAGALX",
            )},
            "supplement": {
                "days_worked": supplement.days_worked if supplement else None,
                "days_paid": supplement.days_paid if supplement else None,
                "hours_worked": supplement.hours_worked if supplement else None,
                "pay_basis": supplement.pay_basis if supplement else basis,
                "ips_base": supplement.ips_base if supplement else None,
                "notes": supplement.notes if supplement else "",
            },
        })
        if issue:
            continue
        line = SimpleNamespace(
            base_salary=gross, overtime=0, commissions=0, bonuses=0, other_income=0,
            absences_discount=0, advances=0, other_discount=discount_other,
            other_discount_note="Descuento original MOV (DESOTR)" if discount_other else "",
            ips_employee=discount_ips, ips_base=base, ips_rate=Decimal("9"),
            gross=gross, total_discounts=discount_ips + discount_other, net=expected_net,
        )
        detail = SimpleNamespace(
            days_worked=days, days_reop=days_paid if basis == "monthly" and days_paid is not None else days,
            days_rei=days_paid if days_paid is not None else days,
            hours_worked=hours, period_start=dstart, period_end=dend,
            payment_method={"1": "Efectivo", "2": "Cheque", "3": "Banco",
                            "4": "Giro"}.get(payment_code, ""),
            overtime_day=0, overtime_night=0, night_surcharge=0, holidays=0,
            family_allowance=0, other_income_detail=0, vacation_pay=0,
            extra_hours=Decimal("0"), extra_hours_documented=True,
            other_amount_bonus=0, other_amount_income=0,
            other_category_bonus="", other_category_income="",
        )
        source.append((line, employee, detail))
    if not diagnostics and not allow_empty:
        errors.append("No existen salarios de funcionarios elegibles con IPS Sí.")
    return source, list(dict.fromkeys(errors)), diagnostics
