"""REOP incorpora trazabilidad de vacaciones sin sumar dos veces el pago."""
from datetime import date

from app.labor_calculator import calculate
from app.models import Vacation
from app.vacation_salary_link import vacation_links_for_period
from tests.test_unified_labor_history import setup_records
from tests.test_labor_suite import salary


def test_overlapping_vacation_with_payment_is_linked_without_prorating():
    db, engine = setup_records()
    try:
        db.add_all([
            Vacation(id=401, employee_id=21, period_year=2025, entitled_days=12,
                     used_days=12, status="Aprobada",
                     start_date=date(2026, 10, 26), end_date=date(2026, 11, 7),
                     paid_amount=1404924, payment_date=date(2026, 10, 23)),
            Vacation(id=402, employee_id=22, period_year=2025, entitled_days=18,
                     used_days=18, status="Aprobada",
                     start_date=date(2026, 10, 26), end_date=date(2026, 11, 12),
                     paid_amount=1800000, payment_date=date(2026, 10, 23)),
            Vacation(id=403, employee_id=21, period_year=2024, entitled_days=12,
                     used_days=12, status="Cancelada",
                     start_date=date(2026, 10, 1), end_date=date(2026, 10, 12)),
        ])
        db.commit()
        october = vacation_links_for_period(db, 11, "2026-10")
        assert len(october) == 1
        assert october[0]["id"] == 401
        assert october[0]["calendar_days_in_period"] == 6
        assert october[0]["paid_amount"] == 1404924
        assert october[0]["payment_verified"] is True
        assert october[0]["url"] == "/app/vacations/401"
        assert vacation_links_for_period(db, 11, "2026-11")[0]["calendar_days_in_period"] == 7
        assert vacation_links_for_period(db, 11, "2026-10", employee_ids=[]) == []
        assert vacation_links_for_period(db, 12, "2026-10")[0]["id"] == 402
    finally:
        db.close()
        engine.dispose()


def test_unpaid_amount_not_inferred_from_dates_or_calendar_days():
    db, engine = setup_records()
    try:
        db.add(Vacation(id=405, employee_id=21, period_year=2025, entitled_days=12,
                        used_days=12, status="Completada",
                        start_date=date(2026, 10, 26), end_date=date(2026, 11, 7)))
        db.commit()
        linked = vacation_links_for_period(db, 11, "2026-10")
        assert linked[0]["paid_amount"] is None
        assert linked[0]["payment_verified"] is False
    finally:
        db.close()
        engine.dispose()


def test_vacation_jornalero_uses_real_daily_rate_not_monthly_divisor():
    data = salary(
        kind="vacation",
        pay_basis="daily", salary="",
        daily_rate="117077", legal_minimum="3044000",
        vacation_quantity="12",
    )
    result = calculate(data)
    assert result["gross"] == 1404924
    assert result["earnings"][0]["label"] == "Remuneración de vacaciones"
    assert any(f["label"] == "Modalidad vacacional" and "Jornalero" in f["value"]
               for f in result["facts"])


def test_vacation_monthly_mode_preserves_existing_formula():
    data = salary(
        kind="vacation", pay_basis="monthly", salary="3044000",
        legal_minimum="3044000", vacation_quantity="12",
    )
    assert calculate(data)["gross"] == 1217600
