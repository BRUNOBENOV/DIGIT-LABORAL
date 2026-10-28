from datetime import date
from decimal import Decimal

import pytest

from app.calculation_operations import (
    validate_advance,
    validate_labor_action,
    validate_telegram,
    validate_work_hours,
)


def test_valid_advance_normalizes_period_and_notes():
    value = validate_advance(
        amount="500000",
        advance_date="2026-10-16",
        salary_period="2026-10",
        status="Descontado",
        notes="  Vale semanal  ",
    )
    assert value["amount"] == 500000
    assert value["advance_date"] == date(2026, 10, 16)
    assert value["salary_period"] == "2026-10"
    assert value["status"] == "Descontado"
    assert value["notes"] == "Vale semanal"


@pytest.mark.parametrize("payload", [
    {"amount": 0, "salary_period": "2026-10"},
    {"amount": -1, "salary_period": "2026-10"},
    {"amount": "abc", "salary_period": "2026-10"},
    {"amount": 100, "salary_period": "2026-13"},
])
def test_invalid_advance_rejected(payload):
    base = {"amount": 100, "advance_date": "2026-10-01", "salary_period": "2026-10"}
    base.update(payload)
    with pytest.raises(ValueError):
        validate_advance(**base)


def test_suspension_requires_valid_date_range():
    with pytest.raises(ValueError, match="requiere fecha inicial y final"):
        validate_labor_action(
            action_type="Suspensión",
            action_date="2026-10-20",
            reason="Motivo",
        )
    with pytest.raises(ValueError, match="fecha final"):
        validate_labor_action(
            action_type="Suspensión",
            action_date="2026-10-20",
            start_date="2026-10-23",
            end_date="2026-10-22",
            reason="Motivo",
        )


def test_valid_permission_can_have_date_range_and_status():
    value = validate_labor_action(
        action_type="Permiso",
        action_date="2026-10-20",
        start_date="2026-11-03",
        end_date="2026-11-03",
        reason="Trámite personal",
        details="Permiso de una jornada",
        status="Aprobado",
    )
    assert value["status"] == "Aprobado"
    assert value["start_date"] == date(2026, 11, 3)
    assert value["end_date"] == date(2026, 11, 3)


def test_work_hours_normalizes_month_and_decimal_values():
    value = validate_work_hours(
        work_date="2026-10-21",
        ordinary_hours="8",
        overtime_hours="1.5",
        night_hours="0",
        holiday_hours="0",
    )
    assert value["work_period"] == "2026-10"
    assert value["ordinary_hours"] == Decimal("8.00")
    assert value["overtime_hours"] == Decimal("1.50")


def test_work_hours_rejects_daily_total_above_24():
    with pytest.raises(ValueError, match="no puede superar 24"):
        validate_work_hours(
            work_date="2026-10-21",
            ordinary_hours=20,
            overtime_hours=3,
            night_hours=2,
            holiday_hours=0,
        )


def test_telegram_generates_code_and_validates_required_content():
    value = validate_telegram(
        company_id=5,
        telegram_type="Comunicación",
        issue_date="2026-10-22",
        destination_address="Av. Principal 100, Ciudad del Este",
        subject="Solicitud de comparecencia",
        body="Se solicita comunicarse con el empleador para tratar el asunto indicado.",
    )
    assert value["telegram_code"].startswith("TC-0005-20261022-")
    assert value["status"] == "Borrador"
    assert len(value["telegram_code"]) <= 40


@pytest.mark.parametrize("field, value", [
    ("destination_address", ""),
    ("subject", ""),
    ("body", ""),
])
def test_telegram_required_fields(field, value):
    payload = {
        "company_id": 5,
        "telegram_type": "Comunicación",
        "issue_date": "2026-10-22",
        "destination_address": "Domicilio",
        "subject": "Asunto",
        "body": "Texto",
    }
    payload[field] = value
    with pytest.raises(ValueError):
        validate_telegram(**payload)
