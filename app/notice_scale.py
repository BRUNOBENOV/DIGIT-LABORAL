"""Calendar-based notice scale shared by the pure calculators and DB service."""
from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def published_rule() -> dict:
    return json.loads((Path(__file__).parent / "data" / "notice_rules.json").read_text(encoding="utf-8"))


def scale_days(start: date, end: date, bands: list[dict] | None = None) -> int:
    # Local import avoids a cycle: the professional calculator also uses this engine.
    from .labor_calculator import anniversary

    if end < start:
        raise ValueError("La fecha de referencia es anterior al ingreso.")
    bands = published_rule()["bands"] if bands is None else bands
    previous = 0
    for index, band in enumerate(bands):
        upper, days = band["max_service_months"], band["notice_days"]
        if type(days) is not int or not 0 < days <= 365:
            raise ValueError("La escala de preaviso contiene días inválidos.")
        if upper is None:
            if index != len(bands) - 1:
                raise ValueError("La escala de preaviso contiene tramos superpuestos.")
        elif type(upper) is not int or upper <= previous:
            raise ValueError("La escala de preaviso contiene límites inválidos.")
        else:
            previous = upper
    if not bands or bands[-1]["max_service_months"] is not None:
        raise ValueError("La escala de preaviso no tiene un tramo final.")
    for band in bands:
        upper = band["max_service_months"]
        if upper is None or end <= anniversary(start, months=upper):
            return band["notice_days"]
    raise ValueError("No se pudo seleccionar un tramo de preaviso.")


def service_tenure(start: date, end: date) -> dict[str, int]:
    from .labor_calculator import anniversary

    if end < start:
        raise ValueError("La fecha de referencia es anterior al ingreso.")
    months = (end.year - start.year) * 12 + end.month - start.month
    if end < anniversary(start, months=months):
        months -= 1
    anchor = anniversary(start, months=months)
    return {"years": months // 12, "months": months % 12, "days": (end - anchor).days}
