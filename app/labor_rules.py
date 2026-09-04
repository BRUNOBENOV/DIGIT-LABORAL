from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class RuleResult:
    value: int | float
    legal_basis: str
    note: str = ""


def completed_years(admission_date: date, as_of: date) -> int:
    if as_of < admission_date:
        return 0
    years = as_of.year - admission_date.year
    if (as_of.month, as_of.day) < (admission_date.month, admission_date.day):
        years -= 1
    return max(0, years)


def months_of_service(admission_date: date, as_of: date) -> int:
    if as_of < admission_date:
        return 0
    months = (as_of.year - admission_date.year) * 12 + as_of.month - admission_date.month
    if as_of.day < admission_date.day:
        months -= 1
    return max(0, months)


def vacation_entitlement_days(admission_date: date, as_of: date) -> RuleResult:
    """Annual vacation scale from Paraguay Labor Code art. 218.

    The function is a control aid, not a substitute for verifying the applicable
    regime, interruptions, proportional rights or collective/contractual benefits.
    """
    years = completed_years(admission_date, as_of)
    if years < 1:
        return RuleResult(0, "Código del Trabajo, art. 218", "Aún no completa un año; revisar derecho proporcional o régimen aplicable.")
    if years <= 5:
        days = 12
    elif years <= 10:
        days = 18
    else:
        days = 30
    return RuleResult(days, "Código del Trabajo, art. 218", f"Antigüedad computada: {years} año(s).")


def preaviso_days(admission_date: date, as_of: date, *, trial_completed: bool = True) -> RuleResult:
    """Notice period scale from art. 87 after the probationary period."""
    if as_of < admission_date:
        return RuleResult(0, "Código del Trabajo, art. 87", "La fecha de referencia es anterior al ingreso.")
    if not trial_completed:
        return RuleResult(0, "Código del Trabajo, arts. 58 y 87", "Revisar primero si el período de prueba sigue vigente.")
    months = months_of_service(admission_date, as_of)
    if months <= 12:
        days = 30
    elif months <= 60:
        days = 45
    elif months <= 120:
        days = 60
    else:
        days = 90
    return RuleResult(days, "Código del Trabajo, art. 87", f"Antigüedad aproximada: {months} mes(es).")


def aguinaldo_amount(total_computable_remunerations: int | float) -> RuleResult:
    amount = round(max(0, float(total_computable_remunerations or 0)) / 12)
    return RuleResult(amount, "Código del Trabajo, arts. 243 y 244", "La base debe incluir solamente remuneraciones legalmente computables.")


def vacation_monthly_base(monthly_salary: int | float, legal_minimum: int | float) -> RuleResult:
    salary = max(0, float(monthly_salary or 0))
    minimum = max(0, float(legal_minimum or 0))
    base = max(salary, minimum)
    return RuleResult(base, "Código del Trabajo, art. 220", "Se utiliza el salario actual cuando supera el mínimo legal aplicable.")


def vacation_amount(monthly_salary: int | float, legal_minimum: int | float, days: int | float) -> RuleResult:
    monthly = vacation_monthly_base(monthly_salary, legal_minimum)
    quantity = max(0, float(days or 0))
    amount = round(float(monthly.value) / 30 * quantity)
    return RuleResult(amount, "Código del Trabajo, arts. 218 y 220", f"Base mensual de control: Gs. {round(float(monthly.value)):,}.".replace(",", "."))


def notice_amount(monthly_average: int | float, days: int | float) -> RuleResult:
    average = max(0, float(monthly_average or 0))
    quantity = max(0, float(days or 0))
    amount = round(average / 30 * quantity)
    return RuleResult(amount, "Código del Trabajo, arts. 87, 90 y 92", "Para el cálculo económico debe revisarse la base promedio legal aplicable.")


def validate_date_range(start: date | None, end: date | None) -> str | None:
    if start and end and end < start:
        return "La fecha final no puede ser anterior a la fecha inicial."
    return None


def validate_vacation_usage(entitled_days: int, used_days: int) -> str | None:
    if entitled_days < 0 or used_days < 0:
        return "Los días no pueden ser negativos."
    if used_days > entitled_days:
        return "Los días utilizados no pueden superar los días concedidos en el mismo registro."
    return None
