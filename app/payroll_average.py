"""Conservative monthly remuneration proposals from closed payroll evidence."""
from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from .labor_calculator import CalculationError, anniversary, checked, gs, number, read_date
from .models import Employee, EmployeeComplianceProfile, Payroll, PayrollComplianceDetail, PayrollLine
from .period_coverage import current_paraguay_date

COMPONENTS = (
    ("base_salary", "Salario base"), ("overtime", "Horas extras"),
    ("commissions", "Comisiones"), ("bonuses", "Bonificaciones"),
    ("other_income", "Otros ingresos"),
)


def propose_monthly_average(
    db: Session, employee: Employee, end: date, *, start: date | None = None,
    today: date | None = None,
) -> dict:
    start = start or employee.admission_date
    if not 1900 <= start.year <= end.year <= 2100 or end < start:
        raise CalculationError("Revisá las fechas de ingreso y egreso.", "end_date")
    window_start = max(start, anniversary(end + timedelta(days=1), months=-6))
    periods = []
    cursor = window_start.replace(day=1)
    while cursor <= end:
        periods.append(cursor.strftime("%Y-%m"))
        cursor = anniversary(cursor, months=1)
    blockers = []
    if start != employee.admission_date:
        blockers.append("La fecha de ingreso difiere del legajo. Revisá las fechas antes de usar el promedio de nóminas.")
    if employee.termination_date and end != employee.termination_date:
        blockers.append("La fecha de egreso difiere de la registrada en el legajo. Revisá el intervalo del cálculo.")
    profile = db.scalar(select(EmployeeComplianceProfile).where(EmployeeComplianceProfile.employee_id == employee.id))
    salary_type = profile.salary_type if profile else "No especificado"
    if salary_type != "Mensual":
        blockers.append("El tipo de salario del legajo no está confirmado como Mensual. Este asistente propone un promedio mensual.")
    if window_start.day != 1 or end.day != monthrange(end.year, end.month)[1]:
        blockers.append("El intervalo incluye fracciones de mes. Revisá el promedio con recibos; no se prorratean haberes automáticamente.")
    if end > (today or current_paraguay_date()):
        blockers.append("La fecha de egreso es futura. Los haberes de períodos todavía no devengados requieren revisión manual.")
    records = db.execute(
        select(Payroll, PayrollLine, PayrollComplianceDetail)
        .join(PayrollLine, PayrollLine.payroll_id == Payroll.id)
        .outerjoin(PayrollComplianceDetail, PayrollComplianceDetail.payroll_line_id == PayrollLine.id)
        .where(Payroll.company_id == employee.company_id,
               PayrollLine.employee_id == employee.id, Payroll.period.in_(periods))
        .order_by(Payroll.period)
    ).all()
    by_period = {payroll.period: (payroll, line, detail) for payroll, line, detail in records}
    rows = []
    for period in periods:
        row = dict(period=period, payroll_id=None, line_id=None, status="Sin nómina",
                   included=False, components=None, gross=None, absences=None, remuneration=None)
        if record := by_period.get(period):
            payroll, line, detail = record
            components = {key: getattr(line, key) for key, _label in COMPONENTS}
            discounts = [line.ips_employee, line.absences_discount, line.advances, line.other_discount]
            valid = (
                all(isinstance(value, int) and value >= 0 for value in [*components.values(), *discounts])
                and line.gross == sum(components.values())
                and line.total_discounts == sum(discounts)
                and line.net == line.gross - line.total_discounts and line.net >= 0
                and line.absences_discount <= line.gross
            )
            if (line.ips_base is None) != (line.ips_rate is None):
                valid = False
            elif line.ips_base is not None:
                rate = Decimal(str(line.ips_rate))
                valid = valid and line.ips_base >= 0 and rate.is_finite() and 0 <= rate <= 100
                if valid:
                    expected_ips = int((Decimal(line.ips_base) * rate / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
                    valid = line.ips_employee == expected_ips
            row.update(payroll_id=payroll.id, line_id=line.id, components=components,
                       gross=line.gross, absences=line.absences_discount,
                       closed_at=payroll.closed_at.replace(tzinfo=None).isoformat() if payroll.closed_at else None)
            period_start = date.fromisoformat(period + "-01")
            period_end = period_start.replace(day=monthrange(period_start.year, period_start.month)[1])
            if not valid:
                row["status"] = "Importes inconsistentes"
            elif payroll.status != "Cerrada":
                row["status"] = "Nómina no cerrada"
            elif not payroll.closed_at:
                row["status"] = "Falta constancia de cierre"
            elif detail and (detail.period_start or detail.period_end) and (
                detail.period_start != period_start or detail.period_end != period_end
            ):
                row["status"] = "Fechas del período incompletas o parciales"
            else:
                row.update(status="Cerrada y consistente", included=True,
                           remuneration=line.gross - line.absences_discount,
                           period_start=period_start.isoformat(), period_end=period_end.isoformat(),
                           period_basis="Período mensual de la nómina")
            if detail:
                row["detail_period_start"] = detail.period_start.isoformat() if detail.period_start else None
                row["detail_period_end"] = detail.period_end.isoformat() if detail.period_end else None
                row["complementary_detail"] = {
                    key: getattr(detail, key) for key in (
                        "night_surcharge", "overtime_day", "overtime_night", "holidays",
                        "vacation_pay", "family_allowance", "other_income_detail",
                    )
                }
        rows.append(row)
    closed_count = sum(row["included"] for row in rows)
    if closed_count != len(periods):
        blockers.append("Faltan nóminas cerradas y consistentes para cubrir todo el intervalo. Los meses faltantes no se completan con cero.")
    total = sum(row["remuneration"] for row in rows if row["included"])
    if closed_count == len(periods) and total <= 0:
        blockers.append("Las remuneraciones registradas no permiten proponer un promedio positivo.")
    available = bool(periods) and not blockers
    average = str((Decimal(total) / len(periods)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if available else None
    basis = dict(
        employee_id=employee.id, company_id=employee.company_id, admission_date=start.isoformat(),
        window_start=window_start.isoformat(), window_end=end.isoformat(), salary_type=salary_type,
        periods=rows, average_salary=average,
    )
    fingerprint = hashlib.sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False).encode()).hexdigest() if available else None
    return dict(
        **basis, is_available=available, fingerprint=fingerprint, expected_count=len(periods),
        closed_count=closed_count, recorded_total=total, divisor_months=len(periods), blockers=blockers,
        component_labels=dict(COMPONENTS),
        methodology="Salario base + horas extras + comisiones + bonificaciones + otros ingresos − ausencias. No se descuentan IPS, anticipos ni otras retenciones.",
        review_note="La propuesta usa los conceptos guardados en las líneas mensuales. Revisá su carácter computable, el detalle complementario y cualquier ajuste antes de aplicarla. Art. 92, inc. b.",
    )


def verify_average_selection(db: Session, employee: Employee | None, data: dict) -> dict | None:
    origin = data.get("average_origin") or "manual"
    if origin not in {"manual", "payroll"}:
        raise CalculationError("Elegí el origen del promedio salarial.", "average_salary")
    if origin == "manual":
        data.pop("average_payroll_fingerprint", None)
        return None
    if data.get("kind") != "settlement" or not employee:
        raise CalculationError("Seleccioná empresa y funcionario para aplicar el promedio de nóminas.", "average_salary")
    if not checked(data, "average_payroll_reviewed"):
        raise CalculationError("Confirmá la revisión de la modalidad mensual y los conceptos del promedio propuesto.", "average_payroll_reviewed")
    proposal = propose_monthly_average(db, employee, read_date(data, "end_date"), start=read_date(data, "start_date"))
    if not proposal["is_available"]:
        raise CalculationError("No se puede aplicar el promedio de nóminas: " + " ".join(proposal["blockers"]), "average_salary")
    if data.get("average_payroll_fingerprint") != proposal["fingerprint"]:
        raise CalculationError("Las fuentes del promedio cambiaron. Consultá y aplicá nuevamente la propuesta antes de calcular.", "average_salary")
    submitted = number(data, "average_salary", "promedio salarial", decimals=2)
    if submitted != Decimal(proposal["average_salary"]):
        raise CalculationError("El promedio ingresado difiere de la propuesta. Aplicala nuevamente o elegí ingreso manual.", "average_salary")
    return proposal


def annotate_average(result: dict, proposal: dict | None) -> dict:
    if proposal is None:
        return result
    result["average_provenance"] = proposal
    result["facts"].extend([
        dict(label="Origen del promedio", value="Nóminas cerradas; conceptos revisados por el liquidador"),
        dict(label="Intervalo del promedio", value=proposal["window_start"] + " a " + proposal["window_end"]),
        dict(label="Meses del promedio", value=str(proposal["divisor_months"])),
    ])
    for row in proposal["periods"]:
        result["notes"].append(
            f"Promedio · {row['period']} · nómina #{row['payroll_id']}, línea #{row['line_id']}: "
            f"bruto Gs. {gs(row['gross'])} − ausencias Gs. {gs(row['absences'])} = Gs. {gs(row['remuneration'])}."
        )
    result["notes"].extend([proposal["methodology"], proposal["review_note"]])
    return result
