"""Conciliación no destructiva de cálculos salariales aprobados con exportaciones.

No genera nóminas ni altera importes: transforma únicamente snapshots ya guardados.
Ante un concepto ambiguo o jornada no documentada, devuelve un bloqueo explicativo.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CalculationRecord, Employee, IntegrationBatch, Payroll, SalaryImportDetail


SALARY_TYPES = ("salary", "suite_salary")
APPROVED = {"Aprobado", "Validado"}


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


def salary_source_summary(db: Session, company_id: int, period: str) -> dict:
    """Conteo informativo para distinguir liquidaciones individuales de nóminas."""
    payroll = db.scalar(select(Payroll).where(Payroll.company_id == company_id, Payroll.period == period))
    records = list(db.scalars(
        select(CalculationRecord).where(
            CalculationRecord.company_id == company_id,
            CalculationRecord.reference_period == period,
            CalculationRecord.calculation_type.in_(SALARY_TYPES),
        ).order_by(CalculationRecord.created_at.desc(), CalculationRecord.id.desc())
    ))
    latest: dict[int, CalculationRecord] = {}
    for item in records:
        if item.employee_id is not None:
            latest.setdefault(item.employee_id, item)
    return {
        "closed_payroll": bool(payroll and payroll.status == "Cerrada" and payroll.closed_at),
        "payroll_status": payroll.status if payroll else "No existe",
        "approved": sum(x.status in APPROVED for x in latest.values()),
        "pending": sum(x.status not in APPROVED for x in latest.values()),
        "total": len(latest),
        "without_employee": sum(x.employee_id is None and x.status in APPROVED for x in records),
    }


def choose_salary_source(db: Session, company_id: int, period: str, requested: str) -> str:
    if requested not in {"auto", "payroll", "approved"}:
        raise ValueError("Seleccioná un origen de salarios válido.")
    if requested != "auto":
        return requested
    summary = salary_source_summary(db, company_id, period)
    if summary["closed_payroll"]:
        return "payroll"
    return "approved" if summary["total"] or summary["without_employee"] else "payroll"


def _professional_line(item: CalculationRecord, inputs: dict, saved: dict, errors: list[str]):
    """Relaciona etiquetas del motor profesional; conceptos no reconocidos bloquean."""
    incomes = {
        "Salario del período": "base_salary",
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
    # La base IPS es un hecho conservado por el motor; no asumir que coincide con bruto.
    base_raw = str(inputs.get("ips_base") or "").strip()
    if base_raw:
        ips_base = _whole(base_raw, "base IPS", errors)
    else:
        facts = saved.get("facts") if isinstance(saved.get("facts"), list) else []
        base_fact = next((str(f.get("value", "")) for f in facts
                          if isinstance(f, dict) and f.get("label") == "Base IPS"), "")
        digits = re.sub(r"[^0-9]", "", base_fact)
        ips_base = _whole(digits if digits else None, "base IPS", errors)
    if inputs.get("apply_ips") in (False, "false", "off"):
        rate = Decimal("0")
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
        other_discount_note=str(inputs.get("other_discount_reason") or ""),
        ips_employee=values["ips_employee"],
        ips_base=ips_base,
        ips_rate=rate,
        gross=_whole(saved.get("gross"), "bruto", errors),
        total_discounts=_whole(saved.get("discounts"), "descuentos", errors),
        net=_whole(saved.get("net"), "neto", errors),
    )
    complements = dict(overtime_day=values["overtime_day"], overtime_night=values["overtime_night"],
                       night_surcharge=values["night_surcharge"], holidays=values["holidays"],
                       family_allowance=values["family_allowance"])
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
        ips_rate=saved.get("ips_rate"),
        gross=_whole(saved.get("gross_computable"), "bruto computable", errors),
        total_discounts=_whole(saved.get("discounts"), "total de descuentos", errors),
        net=_whole(saved.get("net"), "neto", errors),
    )
    return line, dict(overtime_day=0, overtime_night=0, night_surcharge=0, holidays=0, family_allowance=0)


def calculation_fingerprint(item: CalculationRecord) -> str:
    return hashlib.sha256(
        (item.input_json or "{}").encode("utf-8")
        + b"\\n"
        + (item.result_json or "{}").encode("utf-8")
    ).hexdigest()


def _review_data(inputs: dict, batch: IntegrationBatch | None,
                 detail: SalaryImportDetail | None, item: CalculationRecord) -> dict:
    # REOP individual preparado y validado registra jornadas sin alterar el cálculo.
    values = dict(inputs)
    if batch and batch.status in {"Validado", "Presentado", "Aceptado"}:
        additional = _obj(batch.payload_json)
        for key in ("days_worked", "hours_worked", "payment_method", "period_start", "period_end"):
            if key in additional and additional[key] not in (None, ""):
                values[key] = additional[key]
    if detail and detail.source_sha256 == calculation_fingerprint(item):
        values.update({
            "days_worked": detail.days_worked,
            "hours_worked": str(detail.hours_worked),
            "payment_method": detail.payment_method,
            "period_start": detail.period_start.isoformat(),
            "period_end": detail.period_end.isoformat(),
        })
    return values


def approved_salary_records(db: Session, company, period: str) -> tuple[list[tuple], list[str], list[dict]]:
    """Selecciona última versión por legajo, con advertencias y sin resucitar anulados."""
    rows = list(db.scalars(select(CalculationRecord).where(
        CalculationRecord.company_id == company.id,
        CalculationRecord.reference_period == period,
        CalculationRecord.calculation_type.in_(SALARY_TYPES),
    ).order_by(CalculationRecord.created_at.desc(), CalculationRecord.id.desc())))
    if not rows:
        return [], ["No hay cálculos de Salario guardados para esta empresa y período."], []
    selected: dict[int, CalculationRecord] = {}
    errors: list[str] = []
    for item in rows:
        if item.employee_id is None:
            if item.status in APPROVED:
                errors.append(f"Cálculo #{item.id}: no tiene funcionario asociado; debe identificarse antes de exportar.")
            continue
        selected.setdefault(item.employee_id, item)
    if not selected:
        return [], list(dict.fromkeys([*errors, "No hay cálculos de Salario vinculados a legajos."])), []
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
        if item.status not in APPROVED:
            errors.append(f"Legajo {id_}: el cálculo más reciente #{item.id} está «{item.status}»; no se reutiliza una aprobación anterior.")
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
            days = int(days_raw) if days_raw not in (None, "") else -1
        except (TypeError, ValueError):
            days = -1
        if days < 0:
            item_errors.append("falta registrar jornadas trabajadas reales; no equivale automáticamente a días remunerados")
        try:
            hours = Decimal(str(hours_raw)) if hours_raw not in (None, "") else Decimal(0)
        except (TypeError, ValueError):
            hours = Decimal(0)
        if not hours.is_finite() or hours <= 0:
            item_errors.append("faltan horas ordinarias efectivamente trabajadas (no usar divisor horario del salario)")
        if not supplementary.get("payment_method"):
            item_errors.append("falta forma de pago verificada")
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
        detail = SimpleNamespace(
            days_worked=days, hours_worked=hours,
            period_start=p_start, period_end=p_end,
            payment_method=str(supplementary.get("payment_method") or ""),
            overtime_day=complements["overtime_day"],
            overtime_night=complements["overtime_night"],
            night_surcharge=complements["night_surcharge"],
            holidays=complements["holidays"],
            family_allowance=complements["family_allowance"],
            other_income_detail=0,
            vacation_pay=0,
        )
        for error in item_errors:
            errors.append(f"{employee.full_name} (cálculo #{item.id}): {error}.")
        source.append((line, employee, detail))
        diagnostics.append(dict(id=item.id, employee=employee.full_name, status=item.status,
                                warnings=item_errors, origin=item.source or item.calculation_type,
                                supplement={
                                    "days_worked": supplementary.get("days_worked", ""),
                                    "hours_worked": supplementary.get("hours_worked", ""),
                                    "payment_method": supplementary.get("payment_method", ""),
                                    "period_start": supplementary.get("period_start", start.isoformat()),
                                    "period_end": supplementary.get("period_end", end.isoformat()),
                                }))
    return source, list(dict.fromkeys(errors)), diagnostics
