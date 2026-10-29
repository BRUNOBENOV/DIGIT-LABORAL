import pytest
from fastapi import HTTPException

from app.main import calculate_values


def test_salary_uses_explicit_ips_base_when_supplied():
    inputs, results, net = calculate_values(
        calculation_type="salary",
        ips_rate=9,
        gross=1_000_000,
        other_income=200_000,
        other_discount=10_000,
        ips_base=800_000,
        apply_ips=True,
    )
    assert inputs["ips_base"] == 800_000
    assert results["gross_computable"] == 1_200_000
    assert results["ips_base"] == 800_000
    assert results["ips_employee"] == 72_000
    assert results["net"] == net == 1_118_000


def test_salary_falls_back_to_computable_income_for_ips_base():
    _, results, _ = calculate_values(
        calculation_type="salary",
        ips_rate=9,
        gross=1_000_000,
        other_income=200_000,
        apply_ips=True,
    )
    assert results["ips_base"] == 1_200_000
    assert results["ips_employee"] == 108_000


def test_salary_allows_zero_ips_base_when_explicitly_entered():
    _, results, net = calculate_values(
        calculation_type="salary",
        ips_rate=9,
        gross=1_000_000,
        ips_base=0,
        apply_ips=True,
    )
    assert results["ips_base"] == 0
    assert results["ips_employee"] == 0
    assert net == 1_000_000


@pytest.mark.parametrize(
    "kwargs",
    [
        {"gross": -1},
        {"other_income": -1},
        {"other_discount": -1},
        {"ips_base": -1},
        {"salary": -1},
        {"total_remunerations": -1},
        {"hours_quantity": -1},
        {"days": -1},
        {"monthly_hours": 0},
        {"multiplier": 0},
        {"ips_rate": 100.01},
    ],
)
def test_general_calculator_rejects_negative_or_invalid_components(kwargs):
    args = {"calculation_type": "salary", "ips_rate": 9}
    args.update(kwargs)
    with pytest.raises(HTTPException) as error:
        calculate_values(**args)
    assert error.value.status_code == 422


def test_general_salary_rejects_discounts_above_computable_earnings():
    with pytest.raises(HTTPException) as error:
        calculate_values(
            calculation_type="salary",
            ips_rate=9,
            gross=100_000,
            other_discount=100_001,
            apply_ips=False,
        )
    assert error.value.status_code == 422
    assert "superan los haberes" in str(error.value.detail)


def test_general_vacation_uses_minimum_wage_for_selected_month():
    inputs, results, amount = calculate_values(
        calculation_type="vacation",
        ips_rate=9,
        salary=2_000_000,
        days=12,
        reference_period="2026-07",
        minimum_salary=3_044_000,
    )
    assert inputs["minimum_salary"] == 3_044_000
    assert results["salary_base_used"] == 3_044_000
    assert results["daily_value"] == 101_467
    assert amount == 1_217_600


def test_general_vacation_fails_closed_without_a_dated_minimum():
    with pytest.raises(HTTPException) as error:
        calculate_values(
            calculation_type="vacation",
            ips_rate=9,
            salary=2_000_000,
            days=12,
            reference_period="2024-06",
        )
    assert error.value.status_code == 422
