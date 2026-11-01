"""Annual aguinaldo evidence: bounded, tenant-scoped and reproducible."""
from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .labor_calculator import CalculationError, aguinaldo_accrual, amount, gs, number, read_date
from .models import Employee, Payroll, PayrollComplianceDetail, PayrollLine
from .payroll_average import COMPONENTS
from .period_coverage import current_paraguay_date

NO_HISTORY = "No hay nóminas cerradas en este año. Ingrese el monto manualmente según el recibo físico"
METHOD = ("Salario base + horas extras + comisiones + bonificaciones remunerativas − ausencias. "
          "No se restan IPS, anticipos ni retenciones. El detalle complementario no se suma otra vez; "
          "asignación familiar y aporte patronal quedan excluidos. Otros ingresos sin clasificación requieren revisión manual.")
SNAPSHOT_KEYS = ("employee_id", "company_id", "admission_date", "window_start", "window_end",
                 "periods", "annual_remuneration", "aguinaldo_accrued", "is_complete", "fingerprint")


def propose_annual_remuneration(
    db: Session, employee: Employee, end: date, *, start: date | None = None,
    today: date | None = None,
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
    rows, closed_count = [], 0
    for period in periods:
        row = dict(period=period, payroll_id=None, line_id=None, status="Sin nómina",
                   included=False, remuneration=None, components=None)
        if record := by_period.get(period):
            payroll, line, detail = record
            closed_count += payroll.status == "Cerrada"
            components = {key: getattr(line, key) for key, _ in COMPONENTS}
            discounts = {key: getattr(line, key) for key in
                         ("ips_employee", "absences_discount", "advances", "other_discount")}
            period_start = date.fromisoformat(period + "-01")
            period_end = period_start.replace(day=monthrange(end.year, period_start.month)[1])
            expected_start, expected_end = max(period_start, window_start), min(period_end, end)
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
        rows.append(row)
    included_count = sum(row["included"] for row in rows)
    total = sum(row["remuneration"] for row in rows if row["included"])
    available = included_count > 0 and not blockers
    complete = available and included_count == len(periods)
    warnings = list(blockers)
    if not closed_count:
        warnings.append(NO_HISTORY)
    elif not complete:
        warnings.append("Cobertura parcial: faltan períodos cerrados y computables. La suma disponible no completa los meses faltantes con cero; revisá los recibos antes de emitir.")
    annual = total if available else None
    basis = dict(employee_id=employee.id, company_id=employee.company_id, admission_date=start.isoformat(),
                 window_start=window_start.isoformat(), window_end=end.isoformat(), periods=rows,
                 annual_remuneration=annual, aguinaldo_accrued=aguinaldo_accrual(total) if available else None,
                 is_complete=complete)
    fingerprint = hashlib.sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False).encode()).hexdigest() if available else None
    return dict(**basis, fingerprint=fingerprint, is_available=available, expected_count=len(periods),
                included_count=included_count, closed_count=closed_count, recorded_total=total,
                blockers=blockers, warnings=warnings, methodology=METHOD)


def verify_annual_selection(db: Session, employee: Employee | None, data: dict) -> dict | None:
    origin = data.get("annual_origin") or "manual"
    if origin not in {"auto", "manual", "payroll"}:
        raise CalculationError("Elegí el origen de la remuneración anual.", "annual_remuneration")
    if origin != "payroll":
        data["annual_origin"] = "manual"
        data.pop("annual_payroll_fingerprint", None)
        return None
    if data.get("kind") != "settlement" or not employee:
        raise CalculationError("Seleccioná empresa y funcionario para usar las nóminas del año.", "annual_remuneration")
    proposal = propose_annual_remuneration(db, employee, read_date(data, "end_date"), start=read_date(data, "start_date"))
    if not proposal["is_available"] or data.get("annual_payroll_fingerprint") != proposal["fingerprint"]:
        raise CalculationError("Las fuentes de la remuneración anual cambiaron. Calculá desde nóminas nuevamente o elegí ingreso manual.", "annual_remuneration")
    if number(data, "annual_remuneration", "remuneración anual", required=True) != proposal["annual_remuneration"]:
        raise CalculationError("La remuneración anual difiere de las nóminas. Volvé a aplicarlas o elegí ingreso manual.", "annual_remuneration")
    return proposal


def annotate_annual(result: dict, proposal: dict | None) -> dict:
    if proposal is None:
        return result
    result["annual_provenance"] = proposal
    result["facts"].extend([
        dict(label="Origen de la remuneración anual", value="Nóminas cerradas"),
        dict(label="Intervalo anual", value=proposal["window_start"] + " a " + proposal["window_end"]),
        dict(label="Cobertura anual", value=f"{proposal['included_count']} de {proposal['expected_count']} períodos computables"),
    ])
    for row in proposal["periods"]:
        result["notes"].append(
            f"Aguinaldo · {row['period']} · " +
            (f"nómina #{row['payroll_id']}, línea #{row['line_id']}: Gs. {gs(row['remuneration'])}."
             if row["included"] else row["status"] + ". No incluido en la suma disponible.")
        )
    result["notes"].append(proposal["methodology"])
    if not proposal["is_complete"]:
        result.update(partial=True, net_label="Subtotal parcial")
        result["warnings"].extend(proposal["warnings"])
    return result
