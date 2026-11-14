"""Remuneraciones guardadas para el aguinaldo de la liquidación final."""
from __future__ import annotations

import hashlib
import json
import re
from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from .aguinaldo_salary_evidence import settlement_salary_amount
from .legacy_salary_mov_import import EVENT_TYPE as MOV_EVENT_TYPE, event_data as mov_event_data
from .labor_calculator import CalculationError, aguinaldo_accrual, amount, checked, gs, number, read_date
from .models import CalculationRecord, Employee, EmployeeEvent, Payroll, PayrollComplianceDetail, PayrollLine, SalaryImportDetail
from .payroll_average import COMPONENTS
from .period_coverage import current_paraguay_date
from .salary_data import APPROVED, PENDING, SALARY_TYPES, calculation_fingerprint, object_json, select_salary_versions

NO_HISTORY = "No hay remuneraciones guardadas que se puedan aplicar en este intervalo. Revisá los períodos o ingresá el total respaldado."
METHOD = ("Se toma una fuente por mes: nómina cerrada, recibo salarial aprobado o importe del historial salarial para revisar. "
          "Se usan haberes computables antes de IPS, anticipos y retenciones. La asignación familiar y los reintegros identificados "
          "se excluyen. El historial salarial se muestra con el importe original, sin agregar conceptos por separado.")
SNAPSHOT_KEYS = ("employee_id", "company_id", "admission_date", "window_start", "window_end",
                 "periods", "annual_remuneration", "aguinaldo_accrued", "is_complete",
                 "fingerprint", "history_reviewed")


def _saved_salaries(db: Session, employee: Employee, periods: list[str]) -> dict[str, CalculationRecord]:
    versions = defaultdict(list)
    records = db.scalars(
        select(CalculationRecord).where(
            CalculationRecord.company_id == employee.company_id,
            CalculationRecord.employee_id == employee.id,
            CalculationRecord.calculation_type.in_(SALARY_TYPES),
            CalculationRecord.reference_period.in_(periods),
        ).order_by(CalculationRecord.created_at.desc(), CalculationRecord.id.desc())
    )
    for record in records:
        versions[record.reference_period].append(record)
    return {period: select_salary_versions(rows)[employee.id] for period, rows in versions.items()}


def _saved_salary_details(db: Session, company_id: int, records) -> dict[int, SalaryImportDetail]:
    ids = [record.id for record in records if record.status in APPROVED]
    if not ids:
        return {}
    return {
        detail.calculation_record_id: detail for detail in db.scalars(
            select(SalaryImportDetail).where(
                SalaryImportDetail.company_id == company_id,
                SalaryImportDetail.calculation_record_id.in_(ids),
            )
        )
    }


def _apply_salary_record(
    row: dict, record: CalculationRecord, month_start: date, month_end: date,
    expected_start: date, expected_end: date, detail: SalaryImportDetail | None,
) -> None:
    row.update(source="salary", calculation_id=record.id, source_hash=calculation_fingerprint(record),
               calculation_status=record.status)
    if record.status not in APPROVED:
        row["status"] = ("Liquidación salarial anulada o sustituida"
                         if record.status in {"Anulado", "Rectificado"}
                         else "Liquidación salarial pendiente de aprobación")
        return

    inputs, saved = object_json(record.input_json), object_json(record.result_json)
    if any(value and value != row["period"] for value in (
        inputs.get("month"), inputs.get("reference_period"), saved.get("period"),
    )):
        row["status"] = "El período guardado en el recibo no coincide"
        return
    explicit_start, explicit_end = inputs.get("period_start"), inputs.get("period_end")
    if detail and detail.source_sha256 == row["source_hash"] and detail.period_start and detail.period_end:
        source_start, source_end = detail.period_start.isoformat(), detail.period_end.isoformat()
    elif explicit_start or explicit_end:
        source_start, source_end = explicit_start, explicit_end
    else:
        source_start, source_end = month_start.isoformat(), month_end.isoformat()
    row.update(period_start=source_start, period_end=source_end)
    if source_start != expected_start.isoformat() or source_end != expected_end.isoformat():
        row["status"] = "El período no coincide con el intervalo devengado; revisar recibo"
        return

    remuneration, problem = settlement_salary_amount(record, inputs, saved)
    if problem:
        row["status"] = problem
    else:
        row.update(included=True, status="Liquidación salarial aprobada", remuneration=remuneration)


def _apply_salary_history(
    row: dict, events: list[EmployeeEvent], company_code: str, expected_start: date, expected_end: date,
) -> None:
    row.update(source="history")
    if len(events) != 1:
        row["status"] = "Hay varios importes en el historial para este mes; revisá el respaldo"
        return
    event = events[0]
    data = mov_event_data(event.detail) or {}
    row["history_id"] = event.id
    values = data.get("values")
    source_hash = data.get("source_hash")
    if (not isinstance(values, dict) or data.get("period") != row["period"] or data.get("warnings")
            or event.effective_date.day != 1
            or not company_code or str(data.get("company_code") or "").strip() != company_code
            or not isinstance(source_hash, str) or not re.fullmatch("[a-f0-9]{64}", source_hash)):
        row["status"] = "Historial salarial con datos de origen pendientes de revisión"
        return
    currency = str(values.get("MONEDA") or "").strip().casefold().replace(".", "")
    if currency and currency not in {"g", "gs", "pyg", "₲", "guaranies", "guaraníes"}:
        row["status"] = "Moneda del historial pendiente de revisión"
        return

    try:
        original = Decimal(str(values.get("SALARI") or ""))
        first_day = Decimal(str(values.get("PAGDEL") or ""))
        last_day = Decimal(str(values.get("PAGALX") or ""))
        if (not original.is_finite() or not 0 < original <= 2_147_483_647
                or not all(day.is_finite() and 1 <= day <= 31 and day == day.to_integral_value()
                           for day in (first_day, last_day))):
            raise ValueError
        first = expected_start.replace(day=int(first_day))
        last = expected_end.replace(day=int(last_day))
    except (InvalidOperation, ValueError):
        row["status"] = "Importe o fechas del historial pendientes de revisión"
        return
    remuneration = amount(original)
    if remuneration != event.amount:
        row["status"] = "El importe del historial no coincide con su origen"
        return
    row.update(period_start=first.isoformat(), period_end=last.isoformat(),
               source_hash=source_hash, recorded_remuneration=format(original, "f"))
    if first != expected_start or last != expected_end:
        row["status"] = "El historial no cubre el intervalo devengado de este mes"
        return

    # This is a recorded amount, and its classification still needs review.
    # It is usable in the provisional subtotal, with full provenance.
    row.update(included=True, status="Historial salarial · revisar conceptos", remuneration=remuneration)


def propose_annual_remuneration(
    db: Session, employee: Employee, end: date, *, start: date | None = None,
    today: date | None = None, payroll_only: bool = False,
) -> dict:
    start = start or employee.admission_date
    if not 1900 <= start.year <= end.year <= 2100 or end < start:
        raise CalculationError("Revisá las fechas de ingreso y egreso.", "end_date")
    year_start = date(end.year, 1, 1)
    window_start = max(year_start, start)
    periods = [f"{end.year}-{month:02d}" for month in range(window_start.month, end.month + 1)]
    blockers = []
    if start != employee.admission_date:
        blockers.append("La fecha de ingreso difiere del legajo. Revisá el intervalo.")
    if employee.termination_date and end != employee.termination_date:
        blockers.append("La fecha de egreso difiere de la registrada en el legajo.")
    if end > (today or current_paraguay_date()):
        blockers.append("La fecha de egreso es futura. Revisá los haberes todavía no devengados.")
    records = db.execute(
        select(Payroll, PayrollLine, PayrollComplianceDetail)
        .join(PayrollLine, PayrollLine.payroll_id == Payroll.id)
        .outerjoin(PayrollComplianceDetail, PayrollComplianceDetail.payroll_line_id == PayrollLine.id)
        .where(Payroll.company_id == employee.company_id, PayrollLine.employee_id == employee.id,
               Payroll.period.in_(periods)).order_by(Payroll.period)
    ).all()
    by_period = {payroll.period: (payroll, line, detail) for payroll, line, detail in records}
    salaries = {} if payroll_only else _saved_salaries(db, employee, periods)
    salary_details = _saved_salary_details(db, employee.company_id, salaries.values())
    history = defaultdict(list)
    if not payroll_only and not all(
        period in by_period and by_period[period][0].status == "Cerrada" for period in periods
    ):
        for event in db.scalars(
            select(EmployeeEvent).where(
                EmployeeEvent.employee_id == employee.id,
                EmployeeEvent.event_type == MOV_EVENT_TYPE,
                EmployeeEvent.effective_date >= window_start.replace(day=1),
                EmployeeEvent.effective_date <= end,
            ).order_by(EmployeeEvent.effective_date, EmployeeEvent.id)
        ):
            history[event.effective_date.strftime("%Y-%m")].append(event)
    company_code = (employee.company.legacy_code or "").strip() if history else ""
    rows, closed_count = [], 0
    for period in periods:
        period_start = date.fromisoformat(period + "-01")
        period_end = period_start.replace(day=monthrange(end.year, period_start.month)[1])
        expected_start, expected_end = max(period_start, window_start), min(period_end, end)
        row = dict(period=period, payroll_id=None, line_id=None, status="Sin nómina",
                   included=False, remuneration=None, components=None)
        payroll_entry = by_period.get(period)
        closed = payroll_entry is not None and payroll_entry[0].status == "Cerrada"
        if payroll_entry:
            payroll, line, detail = payroll_entry
            closed_count += payroll.status == "Cerrada"
            components = {key: getattr(line, key) for key, _ in COMPONENTS}
            discounts = {key: getattr(line, key) for key in
                         ("ips_employee", "absences_discount", "advances", "other_discount")}
            source_start = detail.period_start if detail and detail.period_start else period_start
            source_end = detail.period_end if detail and detail.period_end else period_end
            complementary = {key: getattr(detail, key) for key in (
                "night_surcharge", "overtime_day", "overtime_night", "holidays", "vacation_pay",
                "family_allowance", "other_income_detail", "employer_ips",
            )} if detail else {}
            row.update(payroll_id=payroll.id, line_id=line.id, components=components, discounts=discounts,
                       gross=line.gross, net=line.net, total_discounts=line.total_discounts,
                       ips_base=line.ips_base, ips_rate=format(Decimal(str(line.ips_rate)).normalize(), "f") if line.ips_rate is not None else None,
                       closed_at=payroll.closed_at.replace(tzinfo=None).isoformat() if payroll.closed_at else None,
                       period_start=source_start.isoformat(), period_end=source_end.isoformat(),
                       complementary_detail=complementary)
            valid = (
                all(isinstance(value, int) and value >= 0 for value in
                    [*components.values(), *discounts.values(), *complementary.values()])
                and line.gross == sum(components.values())
                and line.total_discounts == sum(discounts.values())
                and line.net == line.gross - line.total_discounts and line.net >= 0
                and line.absences_discount <= line.gross
            )
            if (line.ips_base is None) != (line.ips_rate is None):
                valid = False
            elif line.ips_base is not None:
                rate = Decimal(str(line.ips_rate))
                valid = valid and line.ips_base >= 0 and rate.is_finite() and 0 <= rate <= 100
                if valid:
                    valid = line.ips_employee == amount(Decimal(line.ips_base) * rate / 100)
            incomplete_dates = detail and bool(detail.period_start) != bool(detail.period_end)
            if payroll.status != "Cerrada":
                row["status"] = "Nómina no cerrada"
            elif not payroll.closed_at:
                row["status"] = "Falta constancia de cierre"
            elif not valid:
                row["status"] = "Importes inconsistentes"
            elif incomplete_dates or source_start != expected_start or source_end != expected_end:
                row["status"] = "El período no coincide con el intervalo devengado; revisar recibo"
            elif line.other_income or complementary.get("other_income_detail"):
                row["status"] = "Otros ingresos sin clasificación computable; revisar recibo"
            else:
                row.update(included=True, status="Cerrada y computable",
                           remuneration=line.gross - line.absences_discount)
        if not payroll_only and not row["included"]:
            salary = salaries.get(period)
            if salary:
                candidate = dict(period=period, payroll_id=None, line_id=None,
                                 included=False, remuneration=None, components=None)
                _apply_salary_record(candidate, salary, period_start, period_end, expected_start, expected_end,
                                     salary_details.get(salary.id))
                if not closed or candidate["included"]:
                    row = candidate
            if (not row["included"] and period in history
                    and not closed
                    and (not salary or salary.status in PENDING)):
                _apply_salary_history(row, history[period], company_code, expected_start, expected_end)
        rows.append(row)
    included_count = sum(row["included"] for row in rows)
    total = sum(row["remuneration"] for row in rows if row["included"])
    historical_count = sum(row.get("source") == "history" and row["included"] for row in rows)
    available = included_count > 0 and not blockers
    complete = available and included_count == len(periods) and not historical_count
    warnings = list(blockers)
    if not included_count:
        warnings.append(NO_HISTORY)
    elif included_count < len(periods):
        warnings.append("Cobertura parcial: faltan meses con remuneraciones computables. Revisá el detalle y completá los importes faltantes.")
    if historical_count:
        warnings.append("La suma incluye importes del historial salarial pendientes de revisar. Confirmá sus conceptos antes de cerrar la liquidación.")
    annual = total if available else None
    basis = dict(employee_id=employee.id, company_id=employee.company_id, admission_date=start.isoformat(),
                 window_start=window_start.isoformat(), window_end=end.isoformat(), periods=rows,
                 annual_remuneration=annual, aguinaldo_accrued=aguinaldo_accrual(total) if available else None,
                 is_complete=complete)
    origin = "salary_records" if any(row.get("source") for row in rows) else "payroll"
    fingerprint = hashlib.sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False).encode()).hexdigest() if available else None
    return dict(**basis, origin=origin, fingerprint=fingerprint, is_available=available, expected_count=len(periods),
                included_count=included_count, closed_count=closed_count, recorded_total=total,
                can_review_history=available and included_count == len(periods) and historical_count > 0,
                blockers=blockers, warnings=warnings, methodology=METHOD)


def verify_annual_selection(db: Session, employee: Employee | None, data: dict) -> dict | None:
    origin = data.get("annual_origin") or "manual"
    if origin not in {"auto", "manual", "payroll", "salary_records"}:
        raise CalculationError("Elegí el origen de la remuneración anual.", "annual_remuneration")
    if origin in {"auto", "manual"}:
        data["annual_origin"] = "manual"
        data.pop("annual_payroll_fingerprint", None)
        data.pop("annual_history_reviewed", None)
        return None
    if data.get("kind") != "settlement" or not employee:
        raise CalculationError("Seleccioná empresa y funcionario para usar los salarios guardados.", "annual_remuneration")
    proposal = propose_annual_remuneration(
        db, employee, read_date(data, "end_date"), start=read_date(data, "start_date"),
        payroll_only=origin == "payroll",
    )
    if (not proposal["is_available"] or origin != proposal["origin"]
            or data.get("annual_payroll_fingerprint") != proposal["fingerprint"]):
        raise CalculationError("Las fuentes de la remuneración anual cambiaron. Actualizá los salarios guardados o elegí ingreso manual.", "annual_remuneration")
    if number(data, "annual_remuneration", "remuneración anual", required=True) != proposal["annual_remuneration"]:
        raise CalculationError("El importe anual difiere de las fuentes guardadas. Actualizá los salarios o elegí ingreso manual.", "annual_remuneration")
    if not proposal["can_review_history"]:
        data.pop("annual_history_reviewed", None)
    elif checked(data, "annual_history_reviewed"):
        proposal = dict(proposal, history_reviewed=True)
    return proposal


def annotate_annual(result: dict, proposal: dict | None) -> dict:
    if proposal is None:
        return result
    result["annual_provenance"] = proposal
    sources = set()
    for row in proposal["periods"]:
        if not row["included"]:
            status = "Sin registro salarial" if row["status"] == "Sin nómina" else row["status"]
            detail = status + "."
        else:
            if row.get("calculation_id"):
                sources.add("Liquidaciones salariales aprobadas")
                detail = f"liquidación salarial #{row['calculation_id']}"
            elif row.get("history_id"):
                sources.add("Historial salarial revisado" if proposal.get("history_reviewed")
                            else "Historial salarial pendiente de revisión")
                detail = f"historial salarial #{row['history_id']} (importe de origen {row['recorded_remuneration']} Gs.)"
            else:
                sources.add("Nóminas cerradas")
                detail = f"nómina #{row['payroll_id']}, línea #{row['line_id']}"
            detail += f": Gs. {gs(row['remuneration'])}."
        result["notes"].append(f"Aguinaldo · {row['period']} · {detail}")
    result["facts"].extend([
        dict(label="Origen de la remuneración anual", value=" · ".join(sorted(sources))),
        dict(label="Intervalo anual", value=proposal["window_start"] + " a " + proposal["window_end"]),
        dict(label="Cobertura anual", value=f"{proposal['included_count']} de {proposal['expected_count']} meses con importe aplicado"),
    ])
    result["notes"].append(proposal["methodology"])
    if proposal.get("history_reviewed"):
        result["notes"].append("El liquidador confirmó las remuneraciones del historial salarial para este cálculo.")
    elif not proposal["is_complete"]:
        result.update(partial=True, net_label="Subtotal parcial")
        result["warnings"].extend(proposal["warnings"])
    return result
