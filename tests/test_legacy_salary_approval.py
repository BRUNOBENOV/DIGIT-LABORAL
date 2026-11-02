"""Compatibility with historical salary calculations (source='Calculadora').

Approval remains strict: it must reproduce stored concepts and the main amount.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.main import _revalidate_calculation_before_approval, calculate_values


def _historic_salary(*, source="Calculadora", without_input_rate=False,
                     amount_delta=0, altered_result=False):
    inputs, results, amount = calculate_values(
        calculation_type="salary",
        ips_rate=9,
        gross=3_044_000,
        other_income=100_000,
        other_discount=15_000,
        ips_base=3_044_000,
        apply_ips=True,
        reference_period="2026-10",
    )
    if without_input_rate:
        inputs.pop("ips_rate")
    if altered_result:
        results["ips_employee"] += 1
    return SimpleNamespace(
        id=23, calculation_type="salary", source=source,
        input_json=json.dumps(inputs), result_json=json.dumps(results),
        amount=amount + amount_delta,
    )


def test_original_calculadora_source_can_be_approved_after_exact_replay():
    item = _historic_salary()
    _revalidate_calculation_before_approval(item, db=None)
    assert item.source == "Calculadora"


def test_legacy_source_replays_with_preserved_ips_rate_in_result_not_current_config():
    item = _historic_salary(without_input_rate=True)
    _revalidate_calculation_before_approval(item, db=None)


@pytest.mark.parametrize("change", [
    {"amount_delta": 1},
    {"altered_result": True},
])
def test_legacy_source_blocks_inconsistent_amounts_and_components(change):
    item = _historic_salary(**change)
    with pytest.raises(HTTPException) as caught:
        _revalidate_calculation_before_approval(item, db=None)
    assert caught.value.status_code == 409
    assert "no coincide" in caught.value.detail


def test_unknown_source_still_rejected():
    item = _historic_salary(source="Origen externo no verificable")
    with pytest.raises(HTTPException) as caught:
        _revalidate_calculation_before_approval(item, db=None)
    assert caught.value.status_code == 409
    assert "no reconocido" in caught.value.detail


def test_old_calculator_rejects_records_without_replayable_inputs():
    item = _historic_salary()
    item.input_json = "{}"
    with pytest.raises(HTTPException) as caught:
        _revalidate_calculation_before_approval(item, db=None)
    assert caught.value.status_code == 409


@pytest.mark.parametrize("without_input_rate", [False, True])
def test_calculadora_v24_exact_source_approved_only_after_replay(without_input_rate):
    item = _historic_salary(source="Calculadora v2.4", without_input_rate=without_input_rate)
    _revalidate_calculation_before_approval(item, db=None)
    assert item.source == "Calculadora v2.4"


@pytest.mark.parametrize("change", [
    {"amount_delta": 1},
    {"altered_result": True},
])
def test_calculadora_v24_never_bypasses_financial_validation(change):
    item = _historic_salary(source="Calculadora v2.4", **change)
    with pytest.raises(HTTPException) as caught:
        _revalidate_calculation_before_approval(item, db=None)
    assert caught.value.status_code == 409


def test_calculadora_v24_rejects_incompatible_unreplayable_snapshot():
    item = _historic_salary(source="Calculadora v2.4")
    item.input_json = '{"gross":"texto inválido"}'
    with pytest.raises(HTTPException) as caught:
        _revalidate_calculation_before_approval(item, db=None)
    assert caught.value.status_code == 409


def test_calculadora_unknown_version_is_not_automatically_trusted():
    item = _historic_salary(source="Calculadora v2.5")
    with pytest.raises(HTTPException) as caught:
        _revalidate_calculation_before_approval(item, db=None)
    assert caught.value.status_code == 409
    assert "no reconocido" in caught.value.detail
