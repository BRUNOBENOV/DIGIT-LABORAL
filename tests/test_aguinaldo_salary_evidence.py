"""El mismo recibo de octubre debe aparecer en Aguinaldo sin duplicar nóminas."""
import json
from datetime import date
from types import SimpleNamespace

from app.aguinaldo_salary_evidence import salary_calculation_evidence
from app.period_coverage import build_annual_coverage


def receipt(*, status="Borrador", income_label="Salario del periodo",
            gross=3044000, income=3044000, net=3044000):
    return SimpleNamespace(
        id=33, source="Centro laboral", status=status,
        result_json=json.dumps({
            "kind": "salary", "period": "2026-10",
            "earnings": [{"label": income_label, "amount": income}],
            "deductions": [], "gross": gross, "discounts": 0, "net": net,
        }),
        input_json=json.dumps({"kind": "salary", "month": "2026-10"}),
        amount=3044000,
    )


def coverage(entry, *, payroll=None):
    return build_annual_coverage(
        year=2026, admission_date=date(2023, 1, 13),
        termination_date=None, today=date(2026, 11, 6),
        payroll_by_period=payroll or {},
        saved_salary_periods={"2026-10"},
        salary_calculations_by_period={"2026-10": entry},
    )


def test_saved_october_receipt_counts_as_one_remuneration_even_without_payroll():
    data = salary_calculation_evidence(receipt())
    report = coverage(data)
    assert data["gross"] == 3044000
    assert data["amounts_consistent"] is True
    assert data["included_by_default"] is False
    assert report["expected_count"] == 11
    assert report["closed_count"] == 0
    assert report["receipt_count"] == 1
    assert report["documented_period_count"] == 1
    assert report["documented_gross"] == 3044000
    assert report["suggested_total"] == 0
    october = report["periods"][9]
    assert october["status"] == "Recibo pendiente de revisión"
    assert october["salary_record_id"] == 33
    assert october["gross"] == 3044000
    assert october["included_in_suggestion"] is False
    assert report["missing_count"] == 10


def test_approved_consistent_october_receipt_contributes_to_provisional_subtotal():
    data = salary_calculation_evidence(receipt(status="Aprobado"))
    report = coverage(data)
    assert data["included_by_default"] is True
    assert report["receipt_approved_count"] == 1
    assert report["suggested_total"] == 3044000
    assert report["periods"][9]["status"] == "Recibo aprobado"
    assert report["periods"][9]["included_in_suggestion"] is True


def test_closed_payroll_prevents_double_counting_approved_salary_receipt():
    data = salary_calculation_evidence(receipt(status="Aprobado"))
    report = coverage(data, payroll={"2026-10": {
        "status": "Cerrada", "gross": 3200000,
        "base_salary": 3000000, "amounts_consistent": True,
    }})
    assert report["documented_period_count"] == 1
    assert report["receipt_count"] == 1
    assert report["receipt_approved_count"] == 0
    assert report["suggested_total"] == 3200000
    assert report["documented_gross"] == 3200000
    assert "no se suman ambas fuentes" in report["periods"][9]["note"]


def test_salary_components_not_automatically_included_when_unclear_or_inconsistent():
    bonus = salary_calculation_evidence(receipt(
        status="Aprobado", income_label="Bonificación Familiar"))
    assert bonus["gross"] == 3044000
    assert bonus["included_by_default"] is False
    assert "carácter computable" in bonus["note"]

    invalid = salary_calculation_evidence(receipt(
        status="Aprobado", gross=3044001))
    assert invalid["amounts_consistent"] is False
    assert invalid["included_by_default"] is False
    assert invalid["gross"] == 3044001

    legacy = SimpleNamespace(
        id=34, source="Legacy", status="Aprobado",
        input_json=json.dumps({"gross": 3044000}),
        result_json=json.dumps({"gross_computable": 3044000}),
        amount=3044000,
    )
    fallback = salary_calculation_evidence(legacy)
    assert fallback["gross"] == 3044000
    assert fallback["included_by_default"] is False


def test_historical_periods_without_saved_receipts_still_behave_as_before():
    report = build_annual_coverage(
        year=2026, admission_date=date(2026, 1, 1),
        termination_date=None, today=date(2026, 3, 3),
        payroll_by_period={},
        saved_salary_periods={"2026-02"},
    )
    assert report["documented_period_count"] == 0
    assert report["missing_count"] == 3
    assert report["receipt_count"] == 0
    assert report["periods"][1]["status"] == "Solo cálculo guardado"
