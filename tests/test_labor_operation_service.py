from datetime import date

import pytest

from app.labor_operation_service import (
    DISCIPLINE_TYPES,
    OPERATION_LABELS,
    OPERATION_STATUSES,
    OPERATION_TYPES,
    validate_labor_operation,
)


def base_payload(operation_type: str, **overrides):
    values = {
        "operation_type": operation_type,
        "title": "Registro de prueba",
        "effective_date": "2026-10-20",
        "end_date": "",
        "status": OPERATION_STATUSES.get(operation_type, ("Registrado",))[0],
        "notes": "",
        "reference_code": "",
    }
    if operation_type == "hours":
        values.update({
            "regular_hours": "8",
            "overtime_hours": "2",
            "salary_reference": "3044000",
            "monthly_hours": "240",
            "multiplier": "1.5",
        })
    elif operation_type == "advance":
        values.update({"amount": "250000", "deduction_period": "2026-10", "payment_method": "Transferencia"})
    elif operation_type == "discipline":
        values.update({"subtype": "Permiso", "reason": "Trámite personal", "authorized_by": "Jefatura", "quantity": "2", "end_date": "2026-10-20"})
    elif operation_type == "telegram":
        values.update({
            "recipient": "Juan Pérez",
            "recipient_document": "1234567",
            "recipient_address": "Ciudad del Este, Paraguay",
            "sender": "Empresa Demo S.A.",
            "body": "Texto para revisión legal.",
            "legal_review": "Pendiente de revisión",
        })
    values.update(overrides)
    return values


def test_operation_catalog_covers_the_new_submodules():
    assert OPERATION_TYPES == ("hours", "advance", "discipline", "telegram")
    assert set(OPERATION_LABELS) == set(OPERATION_TYPES)
    assert DISCIPLINE_TYPES == ("Amonestación", "Suspensión", "Permiso")


def test_hours_operation_calculates_and_preserves_the_assumptions():
    result = validate_labor_operation(base_payload("hours"), today=date(2026, 10, 28))
    assert result["quantity"] == 10
    assert result["amount"] == 139517
    assert result["payload"]["hourly_value"] == 12683
    assert result["payload"]["multiplier"] == 1.5
    assert "revisar" in result["payload"]["calculation_note"].lower()


@pytest.mark.parametrize("payload, message", [
    ({"regular_hours": "0", "overtime_hours": "0"}, "al menos una hora"),
    ({"regular_hours": "24", "overtime_hours": "1"}, "no puede superar 24"),
    ({"multiplier": "0.5"}, "multiplicador"),
    ({"monthly_hours": "0"}, "horas mensuales"),
])
def test_hours_validates_quantities_and_calculation_inputs(payload, message):
    data = base_payload("hours")
    data.update(payload)
    with pytest.raises(ValueError, match=message):
        validate_labor_operation(data)


def test_advance_requires_positive_integer_amount():
    with pytest.raises(ValueError, match="importe"):
        validate_labor_operation(base_payload("advance", amount="0"))
    with pytest.raises(ValueError, match="entero"):
        validate_labor_operation(base_payload("advance", amount="100.50"))
    result = validate_labor_operation(base_payload("advance"))
    assert result["amount"] == 250000
    assert result["payload"]["deduction_period"] == "2026-10"


def test_suspension_and_permission_require_an_end_date():
    for subtype in ("Suspensión", "Permiso"):
        with pytest.raises(ValueError, match="fecha de fin"):
            validate_labor_operation(base_payload("discipline", subtype=subtype, end_date=""))
    result = validate_labor_operation(base_payload("discipline", subtype="Amonestación", end_date=""))
    assert result["payload"]["subtype"] == "Amonestación"


def test_end_date_cannot_precede_start_date():
    with pytest.raises(ValueError, match="anterior"):
        validate_labor_operation(base_payload("discipline", effective_date="2026-10-22", end_date="2026-10-20"))


def test_telegram_requires_recipient_address_and_body():
    for field in ("recipient", "recipient_address", "sender", "body"):
        with pytest.raises(ValueError, match="obligatorio"):
            validate_labor_operation(base_payload("telegram", **{field: ""}))


def test_invalid_operation_type_status_and_long_text_are_rejected():
    with pytest.raises(ValueError, match="tipo de operación"):
        validate_labor_operation(base_payload("unknown"))
    with pytest.raises(ValueError, match="estado"):
        validate_labor_operation(base_payload("advance", status="Enviado"))
    with pytest.raises(ValueError, match="3.000 caracteres"):
        validate_labor_operation(base_payload("advance", notes="x" * 3001))


def test_numeric_limits_and_bad_dates_are_rejected():
    with pytest.raises(ValueError, match="fecha válida"):
        validate_labor_operation(base_payload("hours", effective_date="2026-02-30"))
    with pytest.raises(ValueError, match="número entero"):
        validate_labor_operation(base_payload("advance", amount="doscientos"))
