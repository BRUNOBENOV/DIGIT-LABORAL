"""Regresiones de liquidación final para modalidades, vacaciones y legislación paraguaya."""
from decimal import Decimal

import pytest

from app.labor_calculator import CalculationError, calculate, settlement_projection
from app.labor_rules import aguinaldo_amount
from tests.test_settlement_legal_cases import settlement_data


def item(result, label):
    return next(row["amount"] for row in result["earnings"] if row["label"] == label)


def test_jornalero_uses_real_jornal_not_salary_divided_by_30_or_26():
    data = settlement_data(
        start_date="2025-08-01", end_date="2026-09-30", reason="resignation",
        pay_basis="daily", salary="117077", daily_rate="117077", days_paid="4",
        pending_days="12", annual_remuneration="468308", apply_ips="",
    )
    result = calculate(data)
    assert item(result, "Jornales del período") == 468_308
    assert item(result, "Vacaciones pendientes") == 1_404_924
    assert result["net"] == 468_308 + 1_404_924 + 39_026
    assert not any("Indemnización ordinaria" in row["label"] for row in result["earnings"])


def test_jornalero_requires_explicit_daily_rate_even_with_positive_salary():
    with pytest.raises(CalculationError) as error:
        calculate(settlement_data(pay_basis="daily", salary="3044000", daily_rate="", reason="resignation"))
    assert error.value.field == "daily_rate"


def test_indemnity_and_notice_use_verified_daily_base_without_guessed_divisor():
    data = settlement_data(
        reason="dismissal", pay_basis="daily", salary="117077",
        daily_rate="117077", days_paid="0", average_salary="0",
        start_date="2024-01-01", end_date="2026-09-30",
        indemnity_daily_base="120000.00",
        indemnity_daily_evidence="Seis meses de recibos y jornales efectivamente pagados.",
    )
    result = calculate(data)
    assert item(result, "Indemnización ordinaria por antigüedad") == 5_400_000
    assert item(result, "Indemnización por preaviso no cumplido") == 5_400_000
    assert result["settlement_projection"]["daily_base"] == "120.000,00"


@pytest.mark.parametrize("change,field", [
    ({"indemnity_daily_base": ""}, "indemnity_daily_base"),
    ({"indemnity_daily_base": "0"}, "indemnity_daily_base"),
    ({"indemnity_daily_evidence": "sin prueba"}, "indemnity_daily_evidence"),
])
def test_jornalero_does_not_approve_indemnity_without_basis_and_evidence(change, field):
    data = settlement_data(
        pay_basis="daily", daily_rate="117077",
        indemnity_daily_base="120000",
        indemnity_daily_evidence="Recibos de los seis meses y registro de jornales.",
    )
    data.update(change)
    with pytest.raises(CalculationError) as error:
        calculate(data)
    assert error.value.field == field


def test_resignation_pays_causadas_but_rejects_proportional():
    with pytest.raises(CalculationError) as error:
        calculate(settlement_data(reason="resignation", pending_days="12", proportional_days="2"))
    assert error.value.field == "proportional_days"
    result = calculate(settlement_data(reason="resignation", pending_days="12", proportional_days="0"))
    assert item(result, "Vacaciones pendientes") == 1_200_000


def test_proportional_before_first_anniversary_can_apply_for_employer_dismissal():
    data = settlement_data(
        start_date="2026-01-01", end_date="2026-07-31",
        reason="dismissal", salary="3044000", average_salary="3044000",
        proportional_days="6", pending_days="0",
    )
    result = calculate(data)
    assert item(result, "Vacaciones proporcionales") == 608_800


@pytest.mark.parametrize("reason", ["resignation", "fixed_term_expiration", "mutual_consent", "death"])
def test_no_automatic_proportionals_on_non_employer_termination(reason):
    with pytest.raises(CalculationError) as error:
        calculate(settlement_data(reason=reason, proportional_days="6"))
    assert error.value.field == "proportional_days"


def test_double_vacations_require_documented_period_and_legal_review():
    with pytest.raises(CalculationError) as error:
        calculate(settlement_data(double_days="12"))
    assert error.value.field == "vacation_double_evidence"
    result = calculate(settlement_data(
        double_days="12", vacation_double_confirmed="on",
        vacation_double_evidence="Período de goce vencido el 01/06/2025, despido posterior acreditado.",
    ))
    assert item(result, "Vacaciones pendientes con pago doble") == 2_400_000


def test_vacations_use_current_dated_minimum_when_salary_is_lower():
    data = settlement_data(
        salary="2000000", average_salary="3000000", days_paid="0",
        end_date="2026-09-30", pending_days="12",
    )
    result = calculate(data)
    assert item(result, "Vacaciones pendientes") == 1_217_600
    assert any(fact["label"] == "Base vacacional mínima controlada" for fact in result["facts"])


def test_special_vacation_scale_requires_verified_minimum():
    data = settlement_data(pending_days="12", vacation_minimum_category="special")
    result = calculate(data)
    assert result["partial"]
    assert any("No se pudo verificar el salario mínimo" in warn for warn in result["warnings"])
    data["vacation_minimum_manual"] = "4000000"
    result = calculate(data)
    assert item(result, "Vacaciones pendientes") == 1_600_000


def test_large_aguinaldo_rounds_with_decimal_not_binary_floats():
    total = Decimal("100000000000.50")
    assert aguinaldo_amount(total).value == 8_333_333_333
