"""Vigencias de salario mínimo usadas por la calculadora profesional.

Valores generales y de aprendizaje transcritos de las publicaciones oficiales
del MTESS. Las actividades con escala propia requieren que el profesional
registre el mínimo aplicable; no se infiere solo desde el rubro de la empresa.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal


SOURCE_2025 = "https://www.mtess.gov.py/?p=30682"
SOURCE_2026 = "https://www.mtess.gov.py/?p=36371"

WAGE_SCALES = (
    {
        "effective_from": date(2025, 7, 1),
        "label": "Resolución MTESS N.º 677/2025",
        "source": SOURCE_2025,
        "monthly": {
            "general_day": 2_899_048,
            "general_night": 3_768_763,
            "apprentice": 1_739_429,
        },
    },
    {
        "effective_from": date(2026, 7, 1),
        "label": "Resolución MTESS N.º 670/2026",
        "source": SOURCE_2026,
        "monthly": {
            "general_day": 3_044_000,
            "general_night": 3_957_200,
            "apprentice": 1_826_400,
        },
    },
)

CATEGORY_LABELS = {
    "general_day": "Actividades diversas no especificadas · jornada diurna",
    "general_night": "Jornada nocturna · escala general",
    "apprentice": "Régimen de aprendizaje / aprendizaje dual",
    "special": "Actividad o categoría con mínimo diferenciado",
}


def minimum_wage_for_period(month: str, category: str, manual_amount=0) -> dict:
    """Return the dated monthly minimum for a salary-period selector.

    None means that this module does not have enough dated data to make a
    reliable automatic comparison. A special scale is never guessed.
    """
    try:
        period = date.fromisoformat(f"{month}-01")
    except (TypeError, ValueError):
        return {"amount": None, "label": CATEGORY_LABELS.get(category, category), "source": None,
                "effective_from": None, "reason": "invalid_period"}

    if category not in CATEGORY_LABELS:
        return {"amount": None, "label": "Escala no reconocida", "source": None,
                "effective_from": None, "reason": "unknown_category"}

    if category == "special":
        try:
            amount = int(Decimal(str(manual_amount or 0)))
        except (ValueError, TypeError, ArithmeticError):
            amount = 0
        if amount > 0:
            return {"amount": amount, "label": CATEGORY_LABELS[category],
                    "source": None, "effective_from": None, "reason": "manual"}
        return {"amount": None, "label": CATEGORY_LABELS[category], "source": None,
                "effective_from": None, "reason": "manual_required"}

    applicable = [scale for scale in WAGE_SCALES if scale["effective_from"] <= period]
    if not applicable:
        return {"amount": None, "label": CATEGORY_LABELS[category], "source": None,
                "effective_from": None, "reason": "historical_scale_unavailable"}

    scale = max(applicable, key=lambda item: item["effective_from"])
    return {
        "amount": scale["monthly"][category],
        "label": CATEGORY_LABELS[category],
        "source": scale["source"],
        "effective_from": scale["effective_from"],
        "rule_label": scale["label"],
        "reason": "official_scale",
    }
