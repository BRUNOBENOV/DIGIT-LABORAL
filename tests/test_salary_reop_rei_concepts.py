"""Separación auditada REOP/REI: días remunerados, asistencia y conceptos contables."""
import json
from decimal import Decimal

from app import official_salary_import as exporter
from app.labor_calculator import calculate
from app.salary_data import calculation_fingerprint
from tests.test_approved_salary_import import FakeSession, case
from tests.test_labor_suite import salary


def approved_case(**changes):
    item, employee, company, detail = case()
    base = dict(kind="salary", salary="3044000", days_paid="30",
                days_worked="21", hours_worked="168", month="2026-10",
                payment_method="Transferencia", commissions="351168")
    base.update(changes)
    data = salary(**base)
    result = calculate(data)
    item.calculation_type = "suite_salary"
    item.source = "Centro laboral"
    item.input_json = json.dumps(data, ensure_ascii=False)
    item.result_json = json.dumps(result, ensure_ascii=False)
    item.amount = result["net"]
    detail.days_worked = int(data["days_worked"])
    detail.hours_worked = Decimal(str(data["hours_worked"]))
    detail.source_sha256 = calculation_fingerprint(item)
    return FakeSession([item], employee, detail), company, result, detail


def test_monthly_worker_reop_uses_paid_days_while_hours_are_effective():
    db, company, result, _ = approved_case()
    rows, errors = exporter.prepare_import(
        db, company, "2026-10", "REOP", source_type="approved", payment_code="3",
    )
    assert not errors, errors
    assert rows[0][5] == 30  # Incluye descansos remunerados: no usa 21 jornadas efectivas.
    assert rows[0][7] == 168
    assert rows[0][10] == 351168
    assert rows[0][9] == 3044000
    assert rows[0][25] == round(Decimal(result["gross"]) * Decimal("0.09"))


def test_daily_worker_reop_works_12_days_and_rei_uses_18_paid_days():
    db, company, result, detail = approved_case(
        pay_basis="daily", salary="", daily_rate="117077",
        days_paid="18", days_worked="12", hours_worked="96",
        commissions="0",
    )
    detail.days_worked, detail.hours_worked = 12, Decimal("96")
    rows, errors = exporter.prepare_import(
        db, company, "2026-10", "REOP", source_type="approved", payment_code="3",
    )
    assert not errors, errors
    assert rows[0][5] == 12
    assert rows[0][7] == 96
    assert rows[0][9] == 18 * 117077
    rei, errors = exporter.prepare_import(
        db, company, "2026-10", "REI", source_type="approved",
        name_order="apellido_primero", rei_category="E",
    )
    assert not errors, errors
    assert rei[0][6] == 18
    assert rei[0][7] == 18 * 117077


def test_manual_overtime_approved_with_real_hours_and_type_maps_to_reop():
    db, company, result, detail = approved_case(
        overtime="14063", overtime_manual_type="day",
        overtime_manual_hours="2",
        overtime_manual_evidence="Marcaciones de octubre firmadas",
    )
    assert any(x["label"] == "Horas extraordinarias diurnas (mínimo 50 %)"
               for x in result["earnings"])
    rows, errors = exporter.prepare_import(
        db, company, "2026-10", "REOP", source_type="approved", payment_code="3",
    )
    assert not errors, errors
    assert rows[0][11] == 14063
    assert rows[0][8] == 2
    assert rows[0][10] == 351168


def test_manual_overtime_without_type_is_a_reviewable_calculation_but_reop_blocks():
    db, company, result, detail = approved_case(overtime="14063")
    assert any("sin cantidad, tipo" in warning for warning in result["warnings"])
    _rows, errors = exporter.prepare_import(
        db, company, "2026-10", "REOP", source_type="approved", payment_code="3",
    )
    assert any("sin mapeo" in error or "horas extraordinarias" in error for error in errors)


def test_each_worker_can_classify_other_income_independently():
    db, company, _result, _ = approved_case(
        bonuses="50000", other_income="70000",
        reop_bonuses_category="premios",
        reop_other_income_category="gratificaciones",
    )
    rows, errors = exporter.prepare_import(
        db, company, "2026-10", "REOP", source_type="approved",
        payment_code="3", other_category="",
    )
    assert not errors, errors
    assert rows[0][14] == 50000
    assert rows[0][17] == 70000
    assert sum(rows[0][9:24]) == rows[0][9] + rows[0][10] + 120000


def test_unclassified_individual_bonus_blocks_reop():
    db, company, _result, _ = approved_case(bonuses="50000")
    _, errors = exporter.prepare_import(
        db, company, "2026-10", "REOP", source_type="approved",
        payment_code="3",
    )
    assert any("otros ingresos no clasificados" in error for error in errors)
