"""Importes para vistas de salarios: solo lectura de resultados guardados.

La columna «amount» de CalculationRecord es NETO. Nunca se reinterpreta ni
se sobrescribe por el bruto para cambiar cómo se presenta una tabla.
"""
from __future__ import annotations

import json


def saved_salary_gross(result_json: str | None) -> int | None:
    """Devuelve el bruto respaldado por el snapshot, o None si no existe.

    No reconstruir el salario a partir del neto ni de fórmulas: los registros
    históricos pueden tener conceptos no recuperables desde su importe neto.
    """
    try:
        result = json.loads(result_json or "{}")
    except (TypeError, ValueError):
        return None
    if not isinstance(result, dict):
        return None
    raw = result.get("gross")
    if type(raw) is int:
        return raw if raw >= 0 else None
    if isinstance(raw, str) and raw.isascii() and raw.isdecimal():
        return int(raw)
    return None
