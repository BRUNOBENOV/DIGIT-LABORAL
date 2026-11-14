"""Evidencia de remuneraciones en cálculos salariales guardados para Aguinaldo.

No recalcula salarios, no declara pagos ni transforma un recibo en comprobante
oficial. Solo consume el snapshot persistido de la liquidación individual.
"""
from __future__ import annotations

import re
import unicodedata

from .salary_data import APPROVED, object_json


def _amount(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 0 <= value <= 2_147_483_647:
        return value
    return None


def _normal_label(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").lower())
    without_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", without_accents).strip()


NON_COMPUTABLE_LABEL_MARKERS = (
    "bonificacion familiar", "asignacion familiar", "viatico", "subsidio",
    "reembolso", "reposo medico", "indemnizacion", "aguinaldo",
    "prestacion social", "movilidad no remunerativa",
)

# Labels emitted by the salary calculator and supported in REOP salary Excel.
# Classification here applies to the settlement calculation, not to the
# gross-coverage report, which continues to show the entire receipt.
COMPUTABLE_LABELS = frozenset({
    "salario del periodo", "jornales del periodo", "salario basico", "comisiones",
    "bonificaciones remunerativas", "otros haberes remunerativos", "feriados",
    "recargo horario nocturno", "complemento salarial", "antiguedad",
    "salario en especie (max 30%)", "regalias", "gratificaciones",
})
COMPUTABLE_PREFIXES = (
    "horas extra", "recargo nocturno ordinario (", "recargo por trabajo en feriado (",
)
EXCLUDED_LABELS = frozenset({
    "bonificacion familiar", "bonificacion familiar manual", "asignacion familiar",
    "reintegro de gastos documentados", "viatico", "viaticos", "reembolso de gastos",
})


def settlement_salary_amount(record, inputs: dict, saved: dict) -> tuple[int | None, str]:
    """Read classified remuneration from the approved salary snapshot."""
    if record.calculation_type == "salary" and "gross_computable" in saved:
        gross = _amount(saved["gross_computable"])
        base = _amount(inputs.get("gross"))
        other = _amount(inputs.get("other_income", 0))
        ips = _amount(saved.get("ips_employee"))
        discounts = _amount(saved.get("discounts"))
        other_discount = _amount(inputs.get("other_discount", 0))
        net = _amount(saved.get("net"))
        if None in (gross, base, other, ips, discounts, other_discount, net):
            return None, "Importes del salario guardado inconsistentes"
        if (gross != base + other or discounts != ips + other_discount
                or gross - discounts != net or net != _amount(record.amount)):
            return None, "Importes del salario guardado inconsistentes"
        if other:
            return None, "Otros ingresos sin clasificación computable; revisar recibo"
        return gross, ""

    evidence = _salary_snapshot_evidence(record, inputs, saved)
    if not evidence["amounts_consistent"]:
        return None, "Importes de la liquidación salarial inconsistentes"

    total = 0
    for row in saved["earnings"]:
        label = _normal_label(row["label"])
        if label in EXCLUDED_LABELS:
            continue
        if label not in COMPUTABLE_LABELS and not label.startswith(COMPUTABLE_PREFIXES):
            return None, "Hay haberes sin clasificación computable; revisá el recibo"
        total += row["amount"]
    # The professional calculator already reflects absences in days paid.
    # Subtract absences only when the received snapshot itemizes them.
    for row in saved["deductions"]:
        label = _normal_label(row.get("label"))
        if label in {"ausencia", "ausencias", "descuento por ausencia", "descuento por ausencias"}:
            total -= row["amount"]
    if total < 0:
        return None, "El descuento por ausencias supera los haberes computables"
    return total, ""


def salary_calculation_evidence(record) -> dict:
    return _salary_snapshot_evidence(record, object_json(record.input_json), object_json(record.result_json))


def _salary_snapshot_evidence(record, inputs: dict, saved: dict) -> dict:
    """Devuelve el bruto guardado y si es utilizable como subtotal orientativo.

    Aprobado/Validado y montos coherentes son necesarios, pero no suficientes:
    ante conceptos potencialmente no computables, se requiere revisión humana.
    """
    status = str(record.status or "Borrador")
    earnings = saved.get("earnings")
    deductions = saved.get("deductions")
    gross = _amount(saved.get("gross"))
    discounts = _amount(saved.get("discounts"))
    net = _amount(saved.get("net"))
    labels: list[str] = []
    breakdown_ok = False

    if isinstance(earnings, list) and isinstance(deductions, list) and earnings:
        if len(earnings) <= 100 and len(deductions) <= 100:
            income_rows = [_amount(row.get("amount")) if isinstance(row, dict) else None for row in earnings]
            expense_rows = [_amount(row.get("amount")) if isinstance(row, dict) else None for row in deductions]
            labels = [_normal_label(row.get("label")) if isinstance(row, dict) else "" for row in earnings]
            if (
                all(amount is not None for amount in income_rows + expense_rows)
                and all(labels) and gross is not None and discounts is not None
                and net is not None
                and sum(income_rows) == gross and sum(expense_rows) == discounts
                and gross - discounts == net == _amount(record.amount)
            ):
                breakdown_ok = True
    else:
        # Registros anteriores: mostrar el bruto registrado si existe, pero
        # no tratarlo como validado si carece de conceptos individuales.
        gross = _amount(saved.get("gross_computable"))
        if gross is None:
            gross = _amount(inputs.get("gross"))
        if gross is None:
            gross = _amount(saved.get("gross"))

    potentially_non_computable = any(
        marker in label for label in labels for marker in NON_COMPUTABLE_LABEL_MARKERS
    )
    eligible = status in APPROVED and breakdown_ok and not potentially_non_computable and bool(gross)
    if potentially_non_computable:
        reason = "Contiene conceptos que requieren determinar su carácter computable."
    elif not breakdown_ok:
        reason = "Los conceptos y los totales del recibo requieren conciliación."
    elif status not in APPROVED:
        reason = "La liquidación individual está pendiente de aprobación interna."
    else:
        reason = "Subtotal bruto de recibo individual aprobado; verificar conceptos para el aguinaldo."

    return {
        "record_id": record.id,
        "source": str(record.source or "Cálculo salarial"),
        "status": status,
        "gross": gross,
        "amounts_consistent": breakdown_ok,
        "included_by_default": eligible,
        "note": reason,
    }
