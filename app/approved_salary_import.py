"""Conciliación no destructiva de cálculos salariales aprobados con exportaciones.

No genera nóminas ni altera importes: transforma únicamente snapshots ya guardados.
Ante un concepto ambiguo o jornada no documentada, devuelve un bloqueo explicativo.
"""
from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CalculationRecord, Employee, EmployeeEvent, IntegrationBatch, Payroll, PayrollLine, SalaryImportDetail


from .salary_data import (SALARY_TYPES, APPROVED, PENDING, select_salary_versions, calculation_fingerprint, merge_attendance)


def salary_export_employee_eligible(employee: Employee, authority: str) -> bool:
    """REOP/REI: IPS Sí es obligatorio; REI conserva además su filtro de activos."""
    if not bool(getattr(employee, "ips_contributor", False)):
        return False
    if authority == "REI":
        return str(getattr(employee, "status", "") or "").strip().casefold() == "activo"
    return authority == "REOP"


def rei_salary_employee_eligible(employee: Employee) -> bool:
    """Compatibilidad: REI exige legajo activo con IPS Sí."""
    return salary_export_employee_eligible(employee, "REI")


def _obj(text: str | None) -> dict:
    try:
        value = json.loads(text or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _whole(value, label: str, errors: list[str], *, required=True) -> int:
    if value is None and required:
        errors.append(f"falta el importe guardado de {label}")
        return 0
    if value is None:
        return 0
    if isinstance(value, bool):
        errors.append(f"{label} no es un importe válido")
        return 0
    try:
        num = Decimal(str(value))
        if not num.is_finite() or num < 0 or num != num.to_integral_value():
            raise ValueError
        return int(num)
    except (TypeError, ValueError):
        errors.append(f"{label} tiene un importe inválido")
        return 0


def salary_source_summary(db: Session, company_id: int, period: str, employee_id: int | None = None,
                          *, authority: str = "REOP") -> dict:
    """Conteo informativo para distinguir liquidaciones individuales de nóminas."""
    payroll = db.scalar(select(Payroll).where(Payroll.company_id == company_id, Payroll.period == period))
    query = select(CalculationRecord).where(
        CalculationRecord.company_id == company_id,
        CalculationRecord.reference_period == period,
        CalculationRecord.calculation_type.in_(SALARY_TYPES),
    )
    if employee_id is not None:
        query = query.where(CalculationRecord.employee_id == employee_id)
    records = list(db.scalars(query.order_by(CalculationRecord.created_at.desc(), CalculationRecord.id.desc())))
    employee_ids = {item.employee_id for item in records if item.employee_id is not None}
    workers = {worker.id: worker for worker in db.scalars(select(Employee).where(
        Employee.company_id == company_id, Employee.id.in_(employee_ids)
    ))} if employee_ids else {}
    records = [item for item in records if item.employee_id is None or (
        item.employee_id in workers and salary_export_employee_eligible(workers[item.employee_id], authority)
    )]
    latest = select_salary_versions(records)
    newest = {}
    for item in records:
        if item.employee_id is not None:
            newest.setdefault(item.employee_id, item)

    # Imported MOV is part of the same salary history, not a separate workflow.
    # It is selected only when this employee/month has no operative approval;
    # an annulled operational record is never resurrected from older evidence.
    mov_ids: set[int] = set()
    if hasattr(db, "execute") and re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", period or ""):
        from .legacy_salary_mov_import import EVENT_TYPE as MOV_EVENT_TYPE
        for (worker,) in db.execute(
            select(Employee).join(EmployeeEvent, EmployeeEvent.employee_id == Employee.id).where(
                Employee.company_id == company_id,
                EmployeeEvent.event_type == MOV_EVENT_TYPE,
                EmployeeEvent.effective_date == date.fromisoformat(period + "-01"),
                *([Employee.id == employee_id] if employee_id is not None else []),
            ).distinct()
        ):
            if salary_export_employee_eligible(worker, authority):
                mov_ids.add(worker.id)
    native_approved = {eid for eid, item in latest.items() if item.status in APPROVED}
    finalized = {eid for eid, item in latest.items() if item.status not in PENDING}
    mov_fallback = mov_ids - finalized
    eligible_ids = native_approved | mov_fallback
    return {
        "closed_payroll": bool(payroll and payroll.status == "Cerrada" and payroll.closed_at),
        "payroll_status": payroll.status if payroll else "No existe",
        "approved": len(eligible_ids),
        "approved_native": len(native_approved),
        "approved_mov": len(mov_fallback),
        "pending": sum(eid not in eligible_ids and item.status not in APPROVED
                       for eid, item in latest.items()),
        "drafts_in_progress": sum(newest[eid].id != item.id for eid, item in latest.items()),
        "total": len(set(latest) | mov_ids),
        "without_employee": sum(x.employee_id is None and x.status in APPROVED for x in records),
        "approved_employee_ids": sorted(eligible_ids),
    }


def choose_salary_source(db: Session, company_id: int, period: str, requested: str, employee_id: int | None = None,
                         *, authority: str = "REOP") -> str:
    if requested not in {"auto", "payroll", "approved", "mov"}:
        raise ValueError("Seleccioná un origen de salarios válido.")
    if requested == "mov":
        # Compatibility for old bookmarks; no special source is required.
        return "approved"
    if requested != "auto":
        return requested
    summary = salary_source_summary(db, company_id, period, employee_id=employee_id, authority=authority)
    if employee_id is not None and summary["approved"]:
        return "approved"
    if summary["closed_payroll"]:
        if summary["approved"]:
            payroll_ids = set(db.scalars(select(PayrollLine.employee_id).join(
                Payroll, Payroll.id == PayrollLine.payroll_id
            ).join(Employee, Employee.id == PayrollLine.employee_id).where(
                Payroll.company_id == company_id, Payroll.period == period,
                Employee.ips_contributor.is_(True),
            )))
            # Un trabajador con IPS No no debe forzar la elección de nómina
            # cuando los trabajadores declarables ya tienen cálculos aprobados.
            payroll_employees = payroll_ids
            if payroll_employees and payroll_employees.issubset(set(summary["approved_employee_ids"])):
                return "approved"
        return "payroll"
    return "approved" if summary["total"] or summary["without_employee"] else "payroll"


REOP_PAYMENT_METHODS = {
    "1": "Efectivo",
    "2": "Cheque",
    "3": "Banco",
    "4": "Giro",
}


def _saved_no_ips(inputs: dict) -> bool:
    """Solo inferir ausencia de descuento si el snapshot guardó IPS desactivado."""
    if "apply_ips" not in inputs:
        return False
    raw = inputs["apply_ips"]
    return raw is False or (isinstance(raw, str) and raw.strip().lower() in {"", "false", "off", "no", "0"})


def _professional_line(item: CalculationRecord, inputs: dict, saved: dict, errors: list[str]):
    """Relaciona etiquetas del motor profesional; conceptos no reconocidos bloquean."""
    incomes = {
        "Salario del período": "base_salary",
        "Jornales del período": "base_salary",
        "Comisiones": "commissions",
        "Bonificaciones remunerativas": "bonuses",
        "Otros haberes remunerativos": "other_income",
        "Horas extraordinarias diurnas (mínimo 50 %)": "overtime_day",
        "Horas extraordinarias nocturnas (100 %)": "overtime_night",
        "Recargo nocturno ordinario (30 % adicional)": "night_surcharge",
        "Recargo por trabajo en feriado (100 % adicional)": "holidays",
        "Bonificación familiar": "family_allowance",
        "Bonificación familiar manual": "family_allowance",
    }
    discounts = {
        "Aporte IPS del trabajador": "ips_employee",
        "Anticipos documentados": "advances",
        "Otros descuentos autorizados": "other_discount",
    }
    values = {k: 0 for k in (*incomes.values(), *discounts.values())}
    for src, mapping, kind in ((saved.get("earnings"), incomes, "haberes"),
                               (saved.get("deductions"), discounts, "descuentos")):
        if not isinstance(src, list):
            errors.append(f"no se conservaron los conceptos detallados de {kind}")
            continue
        for concept in src:
            if not isinstance(concept, dict):
                errors.append(f"concepto de {kind} corrupto")
                continue
            label = str(concept.get("label") or "").strip()
            if label not in mapping:
                errors.append(f"concepto «{label or 'sin nombre'}» sin mapeo comprobado para exportar")
                continue
            values[mapping[label]] += _whole(concept.get("amount"), label, errors)
    # La base IPS debe proceder del snapshot, sin reconstruirla a partir del sueldo.
    # Para un salario guardado explícitamente SIN IPS, cero es el importe correcto:
    # el motor no genera una base imponible ni descuento en ese caso.
    no_ips = _saved_no_ips(inputs)
    base_raw = str(inputs.get("ips_base") or "").strip()
    if base_raw:
        ips_base = _whole(base_raw, "base IPS", errors)
    else:
        facts = saved.get("facts") if isinstance(saved.get("facts"), list) else []
        base_fact = next((str(f.get("value", "")) for f in facts
                          if isinstance(f, dict) and f.get("label") == "Base IPS"), "")
        digits = re.sub(r"[^0-9]", "", base_fact)
        ips_base = 0 if no_ips and not digits else _whole(digits if digits else None, "base IPS", errors)
    if no_ips:
        rate = Decimal("0")
        if values["ips_employee"]:
            errors.append("el cálculo marca IPS desactivado pero conserva un descuento IPS; revisá el cálculo aprobado")
    else:
        raw_rate = inputs.get("employee_rate", inputs.get("ips_rate"))
        if raw_rate is None or str(raw_rate).strip() == "":
            errors.append("falta tasa IPS guardada en el cálculo profesional")
        try:
            rate = Decimal(str(raw_rate)) if raw_rate is not None else None
        except (ValueError, TypeError):
            errors.append("tasa IPS guardada inválida")
            rate = None
    line = SimpleNamespace(
        base_salary=values["base_salary"],
        overtime=values["overtime_day"] + values["overtime_night"],
        commissions=values["commissions"],
        bonuses=values["bonuses"] + values["night_surcharge"] +
                values["holidays"] + values["family_allowance"],
        other_income=values["other_income"],
        absences_discount=0,
        advances=values["advances"],
        other_discount=values["other_discount"],
        other_discount_note=str(inputs.get("discount_reason") or inputs.get("other_discount_reason") or ""),
        ips_employee=values["ips_employee"],
        ips_base=ips_base,
        ips_rate=rate,
        gross=_whole(saved.get("gross"), "bruto", errors),
        total_discounts=_whole(saved.get("discounts"), "descuentos", errors),
        net=_whole(saved.get("net"), "neto", errors),
    )
    manual_type = str(inputs.get("overtime_manual_type") or "").strip()
    manual_hours = inputs.get("overtime_manual_hours")
    raw_extra_hours = (inputs.get("day_extra_hours"), inputs.get("night_extra_hours"))
    if manual_type and manual_type not in {"day", "night"}:
        errors.append("la categoría de horas extras manuales es inválida")
    try:
        extra_hours = sum((Decimal(str(value or "0")) for value in raw_extra_hours), Decimal("0"))
        extra_hours += Decimal(str(manual_hours or "0"))
        if not extra_hours.is_finite() or extra_hours < 0 or extra_hours > 744:
            raise ValueError
    except (ValueError, TypeError, ArithmeticError):
        errors.append("horas extraordinarias guardadas inválidas")
        extra_hours = Decimal("0")
    permitted = {"", "premios", "regalias", "gratificaciones", "grado", "dietas", "complemento", "antiguedad"}
    bonus_category = str(inputs.get("reop_bonuses_category") or "")
    other_category = str(inputs.get("reop_other_income_category") or "")
    if bonus_category not in permitted or other_category not in permitted:
        errors.append("la clasificación de otros ingresos REOP es inválida")
    complements = dict(overtime_day=values["overtime_day"], overtime_night=values["overtime_night"],
                       night_surcharge=values["night_surcharge"], holidays=values["holidays"],
                       family_allowance=values["family_allowance"], extra_hours=extra_hours,
                       extra_hours_documented=bool(any(value not in (None, "") for value in raw_extra_hours) or
                                                   (manual_type and manual_hours not in (None, "", 0, "0"))),
                       other_category_bonus=bonus_category,
                       other_category_income=other_category,
                       other_amount_bonus=values["bonuses"],
                       other_amount_income=values["other_income"])
    return line, complements


def _legacy_line(item: CalculationRecord, inputs: dict, saved: dict, errors: list[str]):
    line = SimpleNamespace(
        base_salary=_whole(inputs.get("gross"), "salario básico", errors),
        overtime=0, commissions=0, bonuses=0,
        other_income=_whole(inputs.get("other_income"), "otros ingresos", errors, required=False),
        absences_discount=0, advances=0,
        other_discount=_whole(inputs.get("other_discount"), "otros descuentos", errors, required=False),
        other_discount_note="",
        ips_employee=_whole(saved.get("ips_employee"), "aporte IPS", errors),
        ips_base=_whole(saved.get("ips_base"), "base IPS", errors),
        ips_rate=(0 if inputs.get("apply_ips") in (False, "false", "off")
                  else saved.get("ips_rate", inputs.get("ips_rate"))),
        gross=_whole(saved.get("gross_computable"), "bruto computable", errors),
        total_discounts=_whole(saved.get("discounts"), "total de descuentos", errors),
        net=_whole(saved.get("net"), "neto", errors),
    )
    return line, dict(overtime_day=0, overtime_night=0, night_surcharge=0, holidays=0, family_allowance=0, extra_hours=Decimal("0"), extra_hours_documented=False)


def _review_data(inputs: dict, batch: IntegrationBatch | None,
                 detail: SalaryImportDetail | None, item: CalculationRecord) -> dict:
    return merge_attendance(inputs, batch, detail, item)


def approved_employee_choices(db: Session, company_id: int, period: str, *, authority: str = "REOP") -> list[Employee]:
    """Use the current approval, preserving it while a new draft is prepared."""
    records = list(db.scalars(
        select(CalculationRecord).where(
            CalculationRecord.company_id == company_id,
            CalculationRecord.reference_period == period,
            CalculationRecord.calculation_type.in_(SALARY_TYPES),
            CalculationRecord.employee_id.is_not(None),
        ).order_by(CalculationRecord.created_at.desc(), CalculationRecord.id.desc())
    ))
    latest = select_salary_versions(records)
    eligible = [eid for eid, item in latest.items() if item.status in APPROVED]
    if not eligible:
        return []
    choices = list(db.scalars(
        select(Employee).where(
            Employee.company_id == company_id, Employee.id.in_(eligible),
        ).order_by(Employee.full_name, Employee.id)
    ))
    return [worker for worker in choices if salary_export_employee_eligible(worker, authority)]


def salary_excluded_records(db: Session, company_id: int, period: str, *, authority: str = "REOP") -> list[dict]:
    """Employees without a current approval; annulments remain a barrier."""
    rows = list(db.scalars(
        select(CalculationRecord).where(
            CalculationRecord.company_id == company_id,
            CalculationRecord.reference_period == period,
            CalculationRecord.calculation_type.in_(SALARY_TYPES),
            CalculationRecord.employee_id.is_not(None),
        ).order_by(CalculationRecord.created_at.desc(), CalculationRecord.id.desc())
    ))
    latest = select_salary_versions(rows)
    # A salary already approved in the imported history is not "pending"
    # merely because a different operational draft exists for that worker.
    known_approvals = set(salary_source_summary(
        db, company_id, period, authority=authority
    )["approved_employee_ids"])
    excluded = [
        {"employee_id": row.employee_id, "calculation_id": row.id, "status": row.status}
        for row in latest.values()
        if row.status not in APPROVED and row.employee_id not in known_approvals
    ]
    if excluded:
        candidates = {e.id: e for e in db.scalars(select(Employee).where(
            Employee.company_id == company_id,
            Employee.id.in_([row["employee_id"] for row in excluded]),
        ))}
        excluded = [
            row for row in excluded
            if row["employee_id"] in candidates
            and salary_export_employee_eligible(candidates[row["employee_id"]], authority)
        ]
    return excluded


def approved_salary_records(db: Session, company, period: str, *, authority: str = "REOP",
                            employee_id: int | None = None, payment_code: str = "") -> tuple[list[tuple], list[str], list[dict]]:
    """Selecciona la aprobación vigente por legajo, sin resucitar anulaciones."""
    query = select(CalculationRecord).where(
        CalculationRecord.company_id == company.id,
        CalculationRecord.reference_period == period,
        CalculationRecord.calculation_type.in_(SALARY_TYPES),
    )
    if employee_id is not None:
        query = query.where(CalculationRecord.employee_id == employee_id)
    rows = list(db.scalars(query.order_by(CalculationRecord.created_at.desc(), CalculationRecord.id.desc())))
    if not rows and not hasattr(db, "execute"):
        return [], ["No hay cálculos de Salario guardados para esta empresa y período."], []
    selected: dict[int, CalculationRecord] = {}
    errors: list[str] = []
    for item in rows:
        if item.employee_id is None:
            if item.status in APPROVED:
                errors.append(f"Cálculo #{item.id}: no tiene funcionario asociado; debe identificarse antes de exportar.")
            continue
    selected = select_salary_versions(rows)
    # The stored MOV salary events are eligible for the same read-only source
    # selection when no current operational approval supersedes them.
    employee_map = {e.id: e for e in db.scalars(select(Employee).where(
        Employee.company_id == company.id, Employee.id.in_(list(selected))
    ))}
    batch_map: dict[int, IntegrationBatch] = {}
    batches = list(db.scalars(select(IntegrationBatch).where(
        IntegrationBatch.company_id == company.id,
        IntegrationBatch.calculation_record_id.in_([x.id for x in selected.values()]),
        IntegrationBatch.authority == "REOP",
        IntegrationBatch.batch_type == "Liquidación salarial individual",
        IntegrationBatch.status.in_(["Validado", "Presentado", "Aceptado"]),
    ).order_by(IntegrationBatch.created_at.desc(), IntegrationBatch.id.desc())))
    for batch in batches:
        batch_map.setdefault(batch.calculation_record_id, batch)
    detail_map = {d.calculation_record_id: d for d in db.scalars(
        select(SalaryImportDetail).where(
            SalaryImportDetail.company_id == company.id,
            SalaryImportDetail.calculation_record_id.in_([x.id for x in selected.values()])
        )
    )}
    source: list[tuple] = []
    diagnostics: list[dict] = []
    for id_, item in sorted(selected.items(), key=lambda pair: pair[0]):
        employee = employee_map.get(id_)
        # Excluir antes de validar importes: IPS No nunca figura en REOP ni REI.
        if employee is not None and not salary_export_employee_eligible(employee, authority):
            continue
        if item.status not in APPROVED:
            if employee_id is not None:
                errors.append(f"Funcionario ID {id_}: no hay aprobación vigente; el registro #{item.id} está «{item.status}». No se reutiliza una aprobación anterior a una anulación.")
            # Company-level exports show excluded drafts separately and
            # enforce consent for the reduced selection at the download gate.
            continue
        if employee is None:
            errors.append(f"Cálculo #{item.id}: el funcionario ya no pertenece a esta empresa.")
            continue
        inputs, saved = _obj(item.input_json), _obj(item.result_json)
        item_errors: list[str] = []
        if not inputs or not saved:
            item_errors.append("faltan datos de entrada o resultado guardados")
        if item.calculation_type == "suite_salary" or item.source == "Centro laboral":
            line, complements = _professional_line(item, inputs, saved, item_errors)
        else:
            line, complements = _legacy_line(item, inputs, saved, item_errors)
        if line.net != item.amount:
            item_errors.append("el neto guardado no coincide con el importe aprobado")
        supplementary = _review_data(inputs, batch_map.get(item.id), detail_map.get(item.id), item)
        days_raw = supplementary.get("days_worked")
        hours_raw = supplementary.get("hours_worked")
        try:
            days_number = Decimal(str(days_raw))
            if isinstance(days_raw, bool) or not days_number.is_finite() or days_number != days_number.to_integral_value():
                raise ValueError
            days = int(days_number)
        except (TypeError, ValueError, ArithmeticError):
            days = -1
        if days < 0:
            item_errors.append("falta registrar jornadas trabajadas reales; no equivale automáticamente a días remunerados")
        try:
            hours = Decimal(str(hours_raw)) if hours_raw not in (None, "") else Decimal(0)
            invalid_hours = not hours.is_finite() or hours < 0 or hours > 744
        except (TypeError, ValueError, ArithmeticError):
            hours = Decimal(0)
            invalid_hours = True
        if invalid_hours:
            hours = Decimal(0)
            if authority == "REOP":
                item_errors.append("las horas ordinarias guardadas son inválidas (rango 0-744)")
        elif authority == "REOP" and hours <= 0:
            item_errors.append("faltan horas ordinarias efectivamente trabajadas (no usar divisor horario del salario)")
        # El medio elegido por el usuario en REOP sirve para registros sin
        # forma guardada. Solo se aplica a esta exportación, nunca altera el
        # cálculo aprobado ni un medio de pago ya registrado.
        payment_from_export = (authority == "REOP"
                               and not str(supplementary.get("payment_method") or "").strip()
                               and payment_code in REOP_PAYMENT_METHODS)
        if payment_from_export:
            supplementary["payment_method"] = REOP_PAYMENT_METHODS[payment_code]
        if authority == "REOP" and not supplementary.get("payment_method"):
            item_errors.append("seleccioná la forma de pago real para este trabajador")
        start = date.fromisoformat(period + "-01")
        end = date.fromisoformat(period + "-01")
        from calendar import monthrange
        end = date(end.year, end.month, monthrange(end.year, end.month)[1])
        try:
            p_start = date.fromisoformat(str(supplementary.get("period_start") or start.isoformat()))
            p_end = date.fromisoformat(str(supplementary.get("period_end") or end.isoformat()))
        except ValueError:
            item_errors.append("fechas del período inválidas")
            p_start, p_end = start, end
        if inputs.get("days_paid") not in (None, "", "30", 30) and not (
            supplementary.get("period_start") and supplementary.get("period_end")
        ):
            item_errors.append("período parcial sin fechas efectivas de liquidación documentadas")
        raw_paid_days = inputs.get("days_paid")
        pay_basis = str(inputs.get("pay_basis") or "monthly")
        if pay_basis not in {"monthly", "daily"}:
            item_errors.append("la modalidad de remuneración no está identificada")
            pay_basis = "monthly"
        try:
            paid_number = Decimal(str(raw_paid_days))
            if (not paid_number.is_finite() or paid_number != paid_number.to_integral_value()
                or paid_number < 0 or paid_number > (31 if pay_basis == "daily" else 30)):
                raise ValueError
            days_paid = int(paid_number)
        except (TypeError, ValueError, ArithmeticError):
            days_paid = None
            if raw_paid_days not in (None, ""):
                item_errors.append("los días remunerados del cálculo son inválidos")
        # REOP: mensualizados informan días pagados, incluidos los descansos legales.
        # Jornaleros: jornadas efectivamente trabajadas. REI: días remunerados
        # guardados en el cálculo; no inferirlos de las horas ordinarias.
        days_reop = days_paid if pay_basis == "monthly" and days_paid is not None else days
        days_rei = days_paid if days_paid is not None else days
        detail = SimpleNamespace(
            days_worked=days, days_reop=days_reop, days_rei=days_rei,
            days_paid=days_paid, pay_basis=pay_basis, hours_worked=hours,
            period_start=p_start, period_end=p_end,
            payment_method=str(supplementary.get("payment_method") or ""),
            overtime_day=complements["overtime_day"],
            overtime_night=complements["overtime_night"],
            night_surcharge=complements["night_surcharge"],
            holidays=complements["holidays"],
            family_allowance=complements["family_allowance"],
            other_income_detail=0,
            vacation_pay=0,
            extra_hours=complements["extra_hours"],
            extra_hours_documented=complements["extra_hours_documented"],
            other_amount_bonus=complements.get("other_amount_bonus", 0),
            other_amount_income=complements.get("other_amount_income", 0),
            other_category_bonus=complements.get("other_category_bonus", ""),
            other_category_income=complements.get("other_category_income", ""),
        )
        for error in item_errors:
            errors.append(f"{employee.full_name} (cálculo #{item.id}): {error}.")
        source.append((line, employee, detail))
        diagnostics.append(dict(id=item.id, employee=employee.full_name, status=item.status,
                                warnings=item_errors, origin=item.source or item.calculation_type,
                                attendance_origins=supplementary.get("attendance_origins", {}),
                                payment_from_export=payment_from_export,
                                supplement={
                                    "days_worked": supplementary.get("days_worked", ""),
                                    "days_reop": days_reop, "days_rei": days_rei,
                                    "days_paid": days_paid,
                                    "hours_worked": supplementary.get("hours_worked", ""),
                                    "payment_method": supplementary.get("payment_method", ""),
                                    "period_start": supplementary.get("period_start", start.isoformat()),
                                    "period_end": supplementary.get("period_end", end.isoformat()),
                                }))
    if hasattr(db, "execute"):
        from .historical_mov_salary_export import mov_salary_records
        # Drafts alone do not hide an earlier incorporated approval. An
        # annulment or actual operational approval does supersede that MOV.
        blocked_ids = {eid for eid, item in selected.items() if item.status not in PENDING}
        historical, historical_errors, _ = mov_salary_records(
            db, company, period, authority=authority, employee_id=employee_id,
            payment_code=payment_code,
            exclude_employee_ids=blocked_ids, allow_empty=True,
        )
        source.extend(historical)
        errors.extend(historical_errors)
    if not source and not errors:
        errors.append("No hay salarios de funcionarios con IPS Sí guardados en esta empresa y período.")
    return source, list(dict.fromkeys(errors)), diagnostics
