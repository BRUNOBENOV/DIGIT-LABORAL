from datetime import date, timedelta

import pytest

from app.medical_exam_service import (
    MEDICAL_EXAM_RESULTS,
    MEDICAL_EXAM_TYPES,
    generate_medical_exam_code,
    medical_exam_expiry_state,
    parse_medical_exam_date,
    validate_medical_exam_fields,
)


def valid_payload(**overrides):
    payload = {
        "company_id": 12,
        "exam_code": "",
        "exam_type": "Ingreso",
        "exam_date_raw": "2026-10-20",
        "result": "Apto",
        "expires_on_raw": "2027-10-20",
        "observations": "",
        "today": date(2026, 10, 28),
    }
    payload.update(overrides)
    return payload


def test_medical_exam_select_options_are_fixed():
    assert MEDICAL_EXAM_TYPES == ("Ingreso", "Periódico", "Salida", "Especial")
    assert MEDICAL_EXAM_RESULTS == ("Apto", "No apto", "Observaciones")


def test_medical_exam_dates_are_parsed_and_code_is_generated():
    result = validate_medical_exam_fields(**valid_payload())
    assert result["exam_date"] == date(2026, 10, 20)
    assert result["expires_on"] == date(2027, 10, 20)
    assert result["exam_code"].startswith("EM-0012-20261020-")
    assert len(result["exam_code"]) <= 40


def test_custom_exam_code_is_normalized_and_observations_trimmed():
    result = validate_medical_exam_fields(**valid_payload(exam_code="  exm-2026/42  ", observations="  Control anual  "))
    assert result["exam_code"] == "EXM-2026/42"
    assert result["observations"] == "Control anual"


@pytest.mark.parametrize("field", ["exam_date_raw", "expires_on_raw"])
def test_missing_exam_dates_are_rejected(field):
    with pytest.raises(ValueError, match="obligatoria"):
        validate_medical_exam_fields(**valid_payload(**{field: ""}))


def test_invalid_calendar_date_is_rejected():
    with pytest.raises(ValueError, match="fecha válida"):
        parse_medical_exam_date("2026-02-30", "fecha del examen", today=date(2026, 10, 28))


def test_future_exam_date_is_rejected():
    with pytest.raises(ValueError, match="no puede ser futura"):
        validate_medical_exam_fields(**valid_payload(exam_date_raw="2026-10-29"))


def test_expiration_cannot_precede_exam_date():
    with pytest.raises(ValueError, match="no puede ser anterior"):
        validate_medical_exam_fields(**valid_payload(expires_on_raw="2026-10-19"))


@pytest.mark.parametrize("field,value", [
    ("exam_type", "Preocupacional"),
    ("result", "Pendiente"),
])
def test_unapproved_values_are_rejected(field, value):
    with pytest.raises(ValueError, match="válido"):
        validate_medical_exam_fields(**valid_payload(**{field: value}))


def test_exam_code_rejects_unexpected_characters():
    with pytest.raises(ValueError, match="El código"):
        validate_medical_exam_fields(**valid_payload(exam_code="EXM <script>"))


def test_observations_have_a_length_limit():
    with pytest.raises(ValueError, match="3.000 caracteres"):
        validate_medical_exam_fields(**valid_payload(observations="x" * 3001))


def test_expiry_alert_states():
    today = date(2026, 10, 28)
    assert medical_exam_expiry_state(today - timedelta(days=1), today=today) == "Vencido"
    assert medical_exam_expiry_state(today, today=today) == "Por vencer"
    assert medical_exam_expiry_state(today + timedelta(days=30), today=today) == "Por vencer"
    assert medical_exam_expiry_state(today + timedelta(days=31), today=today) == "Vigente"


def test_generated_codes_change_when_random_suffix_changes():
    exam_date = date(2026, 10, 20)
    first = generate_medical_exam_code(12, exam_date, token="ABC123")
    second = generate_medical_exam_code(12, exam_date, token="DEF456")
    assert first == "EM-0012-20261020-ABC123"
    assert second == "EM-0012-20261020-DEF456"
