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
