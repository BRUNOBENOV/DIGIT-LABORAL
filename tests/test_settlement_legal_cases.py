from app.calculator_fields import GROUPS
from app.labor_calculator import calculate


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
