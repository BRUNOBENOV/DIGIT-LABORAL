"""Regresión del cálculo salarial único: mensualizado y jornalero."""
import pytest

from app.labor_calculator import CalculationError, calculate
from tests.test_labor_suite import salary, web_case


def test_salary_monthly_keeps_divisor_30():
    result = calculate(salary(salary="3044000", days_paid="30", pay_basis="monthly"))
    assert result["gross"] == 3_044_000
    assert result["net"] == 2_770_040
    assert {"label": "Modalidad salarial", "value": "Mensualizado · divisor 30"} in result["facts"]


def test_salary_daily_reproduces_journal_reference_without_importing_mensual_divisor():
    result = calculate(salary(salary="3044000", days_paid="30", pay_basis="daily"))
    assert result["gross"] == 3_512_308
    assert result["net"] == 3_196_200
    assert {"label": "Modalidad salarial", "value": "Jornalero · divisor 26"} in result["facts"]
    assert any("más de 26" in warning for warning in result["warnings"])


def test_salary_daily_pact_rate_and_overtime_share_daily_base():
    result = calculate(salary(
        salary="3044000", days_paid="10", pay_basis="daily",
        daily_rate="120000", day_extra_hours="2"
    ))
    assert result["gross"] == 1_245_000
    assert result["net"] == 1_132_950
    assert any(item["label"] == "Horas extraordinarias diurnas (mínimo 50 %)"
               and item["amount"] == 45_000 for item in result["earnings"])


@pytest.mark.parametrize("data,field", [
    ({"pay_basis": "unknown"}, "pay_basis"),
    ({"pay_basis": "monthly", "days_paid": "31"}, "days_paid"),
    ({"pay_basis": "daily", "days_paid": "32"}, "days_paid"),
    ({"pay_basis": "daily", "daily_rate": "-1"}, "daily_rate"),
    ({"pay_basis": "daily", "daily_rate": "0"}, "daily_rate"),
])
def test_salary_rejects_invalid_modality_or_days(data, field):
    with pytest.raises(CalculationError) as exc:
        calculate(salary(**data))
    assert exc.value.field == field


def test_salary_legacy_entry_redirects_to_one_professional_calculator(web_case):
    client, *_ = web_case
    response = client.get("/app/calculations?tipo=salary", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/app/liquidaciones?tipo=salary")


def test_professional_jornal_exports_as_salary_not_unmapped_income():
    from app.approved_salary_import import _professional_line
    inputs = salary(salary="3044000", days_paid="26", pay_basis="daily")
    result = calculate(inputs)
    errors = []
    line, complements = _professional_line(None, inputs, result, errors)
    assert errors == []
    assert line.base_salary == 3_044_000
    assert line.gross == result["gross"]
    assert line.ips_base == 3_044_000
