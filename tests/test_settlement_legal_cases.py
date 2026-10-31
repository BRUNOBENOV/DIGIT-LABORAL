import pytest

from app.calculator_fields import GROUPS
from app.labor_calculator import CalculationError, calculate, settlement_projection


def settlement_data(**overrides):
    data = {
        field["name"]: field["value"]
        for group in GROUPS["settlement"]
        for field in group["fields"]
    }
    data.update({
        "kind": "settlement",
        "issued_date": "2026-10-28",
        "employer": "Empresa de prueba",
        "ruc": "80000000-0",
        "employee": "Persona de prueba",
        "ci": "1000000",
        "salary": "3000000",
        "days_paid": "0",
        "start_date": "2019-01-01",
        "end_date": "2025-07-02",
        "reason": "dismissal",
        "indefinite": "on",
        "trial_completed": "on",
        "protected": "",
        "average_salary": "3000000",
        "notice_served": "0",
        "pending_days": "0",
        "double_days": "0",
        "proportional_days": "0",
        "annual_remuneration": "0",
        "aguinaldo_paid": "0",
        "apply_ips": "on",
        "ips_rate": "9",
        "ips_base": "0",
        "ips_reason": "Sin haberes sujetos a IPS pendientes en el ejemplo.",
        "advances": "0",
        "other_discount": "0",
        "discount_reason": "",
        "notes": "Caso ficticio para pruebas automatizadas.",
    })
    data.update(overrides)
    return data


def earning_amount(result, label):
    return next(item["amount"] for item in result["earnings"] if item["label"] == label)


def test_worker_justified_withdrawal_calculates_as_conditional_statutory_scenario():
    result = calculate(settlement_data(reason="worker_justified"))

    assert earning_amount(result, "Indemnización ordinaria por antigüedad") == 10_500_000
    assert earning_amount(result, "Indemnización por preaviso no cumplido") == 6_000_000
    assert result["partial"] is True
    assert any("artículo 84" in warning for warning in result["warnings"])
    assert any(item["legal"] == "Arts. 85, 91 y 92" for item in result["earnings"])


def test_service_time_includes_years_months_days_and_calendar_days():
    result = calculate(settlement_data())
    facts = {item["label"]: item["value"] for item in result["facts"]}

    assert facts["Antigüedad exacta"] == "6 años, 6 meses y 1 día"
    assert facts["Días calendario del vínculo"] == "2375"


def test_ten_year_stability_does_not_add_ordinary_severance_automatically():
    result = calculate(settlement_data(start_date="2015-01-01", end_date="2026-06-01"))

    assert result["partial"] is True
    assert not any(item["label"] == "Indemnización ordinaria por antigüedad" for item in result["earnings"])
    assert not any(item["label"] == "Indemnización por preaviso no cumplido" for item in result["earnings"])
    assert any("estabilidad laboral" in warning for warning in result["warnings"])


def test_special_protected_case_does_not_use_ordinary_indemnity_formula():
    result = calculate(settlement_data(protected="on"))

    assert result["partial"] is True
    assert not any(item["label"] == "Indemnización ordinaria por antigüedad" for item in result["earnings"])
    assert any("protección laboral especial" in warning for warning in result["warnings"])


def test_employer_alleged_just_cause_is_a_partial_result():
    result = calculate(settlement_data(reason="justified"))

    assert result["partial"] is True
    assert result["net_label"] == "Subtotal parcial"
    assert any("no declara probada esa causa" in warning for warning in result["warnings"])
    assert not any(item["label"] == "Indemnización ordinaria por antigüedad" for item in result["earnings"])


def test_trial_not_completed_does_not_calculate_ordinary_indemnity():
    result = calculate(settlement_data(trial_completed=""))

    assert result["partial"] is True
    assert not any(item["label"] == "Indemnización ordinaria por antigüedad" for item in result["earnings"])
    assert any("período de prueba" in warning for warning in result["warnings"])


def test_other_exit_causes_are_explicitly_marked_partial():
    for reason, expected_text in (
        ("fixed_term_expiration", "artículo 83"),
        ("mutual_consent", "artículo 78(b)"),
        ("death", "artículo 91"),
        ("other", "no está parametrizada"),
    ):
        result = calculate(settlement_data(reason=reason))
        assert result["partial"] is True
        assert result["net_label"] == "Subtotal parcial"
        assert any(expected_text in warning for warning in result["warnings"])


def test_settlement_fields_offer_distinct_termination_reasons():
    reason = next(field for group in GROUPS["settlement"] for field in group["fields"] if field["name"] == "reason")
    values = {value for value, _label in reason["attrs"]["options"]}

    assert {"dismissal", "resignation", "justified", "worker_justified", "fixed_term_expiration", "mutual_consent", "death", "other"} <= values


def stability_data(**overrides):
    data = settlement_data(
        start_date="1999-02-11", end_date="2026-10-31", salary="3044000",
        average_salary="3185221.66", severance_regime="stability_double",
        stability_basis="worker_option", stability_confirmed="on",
        stability_evidence="Acta sintética de opción del trabajador, con revisión profesional.",
    )
    data.update(overrides)
    return data


def test_confirmed_stability_computes_840_days_and_90_notice_with_monthly_base_30():
    result = calculate(stability_data(proportional_days="22", annual_remuneration="19037824"))
    facts = {item["label"]: item["value"] for item in result["facts"]}
    assert result["partial"] is False
    assert facts["Antigüedad exacta"] == "27 años, 8 meses y 20 días"
    assert facts["Años computables para indemnización"] == "28"
    assert facts["Días de indemnización"] == "840"
    assert facts["Días de preaviso a pagar"] == "90"
    assert earning_amount(result, "Indemnización doble por estabilidad") == 89_186_206
    assert earning_amount(result, "Indemnización por preaviso no cumplido") == 9_555_665
    assert earning_amount(result, "Vacaciones proporcionales") == 2_232_267
    assert result["net"] == 102_560_623
    assert "3.185.221,66 / 30 × 15 × 28 × 2" in result["earnings"][0]["formula"]
    assert not any("Indemnización ordinaria" in row["label"] for row in result["earnings"])
    assert any("Acta sintética" in note for note in result["notes"])


@pytest.mark.parametrize("overrides,field", [
    ({"stability_basis": ""}, "stability_basis"),
    ({"stability_basis": "inventado"}, "stability_basis"),
    ({"stability_evidence": ""}, "stability_evidence"),
    ({"stability_evidence": "revisado"}, "stability_evidence"),
    ({"stability_confirmed": ""}, "stability_confirmed"),
])
def test_double_indemnity_requires_valid_basis_evidence_and_confirmation(overrides, field):
    with pytest.raises(CalculationError) as error:
        calculate(stability_data(**overrides))
    assert error.value.field == field


@pytest.mark.parametrize("overrides", [
    {"start_date": "2017-01-01"}, {"reason": "resignation"},
    {"reason": "worker_justified"}, {"indefinite": ""},
    {"trial_completed": ""}, {"protected": "on"},
])
def test_stability_confirmation_cannot_bypass_an_incompatible_regime(overrides):
    with pytest.raises(CalculationError) as error:
        calculate(stability_data(**overrides))
    assert error.value.field == "severance_regime"


@pytest.mark.parametrize("served,expected", [("", 9_555_665), ("0", 9_555_665), ("30", 6_370_443), ("90", 0)])
def test_confirmed_stability_subtracts_notice_actually_served(served, expected):
    result = calculate(stability_data(notice_served=served))
    notice = [row["amount"] for row in result["earnings"] if "preaviso no cumplido" in row["label"]]
    assert sum(notice) == expected
    assert earning_amount(result, "Indemnización doble por estabilidad") == 89_186_206


def test_overserved_notice_and_protected_debt_remain_rejected_with_double_indemnity():
    with pytest.raises(CalculationError) as error:
        calculate(stability_data(notice_served="91"))
    assert error.value.field == "notice_served"
    with pytest.raises(CalculationError) as error:
        calculate(stability_data(other_discount="1", discount_reason="Deuda sintética"))
    assert error.value.field == "other_discount"


@pytest.mark.parametrize("end,days", [("2026-08-11", 810), ("2026-08-12", 840)])
def test_double_indemnity_counts_only_fraction_strictly_above_six_months(end, days):
    result = calculate(stability_data(end_date=end))
    assert result["settlement_projection"]["days"] == days


def test_unconfirmed_stability_projection_explains_potential_days_without_summing_them():
    result = calculate(stability_data(severance_regime="auto"))
    assert result["partial"] is True
    projection = result["settlement_projection"]
    assert projection["ordinary_days"] == 420
    assert projection["notice_due"] == 90
    assert projection["days"] is None and projection["severance"] is None
    assert not any("Indemnización" in row["label"] for row in result["earnings"])
    assert any("Indemnización y preaviso" in warning for warning in result["warnings"])


def test_projection_does_not_require_legal_confirmation_or_a_salary_to_show_days():
    projection = settlement_projection(stability_data(average_salary="", stability_confirmed=""))
    assert projection["days"] == 840
    assert projection["notice_payable"] == 90
    assert projection["severance"] is None


@pytest.mark.parametrize("overrides,field", [
    ({"severance_regime": "manual"}, "severance_regime"),
    ({"average_salary": "3185221.666"}, "average_salary"),
    ({"average_salary": "-1"}, "average_salary"),
    ({"average_salary": "0"}, "average_salary"),
])
def test_stability_rejects_invalid_regime_and_average_precision(overrides, field):
    with pytest.raises(CalculationError) as error:
        calculate(stability_data(**overrides))
    assert error.value.field == field
