"""Strict, read-only reconciliation of an IPS REI planilla with Digit records.

The browser extension reads an already open, authenticated REI planilla.
No uploads, external writes, calculations or changes to stored salaries occur here.
"""
from __future__ import annotations

import re

PERIOD = re.compile(r"^20\d{2}-(?:0[1-9]|1[0-2])$")
MAX_ROWS = 500
MAX_SALARY = 2_147_483_647


class SnapshotError(ValueError):
    pass


def digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def normalized_document(value) -> str:
    document = digits(value)
    if not 4 <= len(document) <= 15:
        raise SnapshotError("La planilla contiene una cédula inválida o vacía.")
    return document


def strict_int(value, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise SnapshotError(f"El campo {name} no es un entero válido.")
    return value


def validate_snapshot(payload: dict, expected_patronal: str, selected_period: str) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("source") != "IPS_REI":
        raise SnapshotError("La fuente no corresponde a una planilla REI del IPS.")
    if not PERIOD.fullmatch(selected_period or ""):
        raise SnapshotError("Seleccioná un período válido, por ejemplo 2026-10.")
    if payload.get("period") != selected_period:
        raise SnapshotError("El período visible en REI no coincide con el período seleccionado en Digit.")
    registered = digits(expected_patronal)
    declared = digits(payload.get("patronal"))
    if not registered:
        raise SnapshotError("Completá el N.º Patronal IPS de la empresa en Digit antes de conciliar.")
    if not declared or declared != registered:
        raise SnapshotError("El número patronal de la planilla IPS no coincide con el de la empresa en Digit.")
    values = payload.get("rows")
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_ROWS:
        raise SnapshotError("La planilla debe contener entre 1 y 500 trabajadores.")
    rows, seen = [], set()
    for index, raw in enumerate(values, 1):
        if not isinstance(raw, dict):
            raise SnapshotError(f"Fila {index}: estructura incorrecta.")
        document = normalized_document(raw.get("document"))
        if document in seen:
            raise SnapshotError(f"La cédula {document} figura más de una vez en la planilla.")
        seen.add(document)
        name = str(raw.get("name") or "").strip()
        if not name or len(name) > 180:
            raise SnapshotError(f"Fila {index}: nombre del trabajador inválido.")
        days = strict_int(raw.get("days_ips"), "días declarados IPS", 31)
        # Salary 'a pagar' and 'real' on the IPS sheet are declared values,
        # not a Digit-approved gross, actual attendance or wage payment proof.
        salary_paid = strict_int(raw.get("salary_paid_ips"), "salario a pagar IPS", MAX_SALARY)
        salary_real = strict_int(raw.get("salary_real_ips"), "salario real IPS", MAX_SALARY)
        movement = str(raw.get("movement") or "").strip().upper()
        if len(movement) > 40:
            raise SnapshotError(f"Fila {index}: movimiento demasiado largo.")
        rows.append({
            "document": document, "name": name, "days_ips": days,
            "salary_paid_ips": salary_paid, "salary_real_ips": salary_real,
            "movement": movement, "source": "IPS REI · Consulta Planillas",
        })
    return rows
