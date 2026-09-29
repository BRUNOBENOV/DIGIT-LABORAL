from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import HTTPException
from pydantic import BeforeValidator


def _blank_query_id(value):
    """A browser's unselected option is an empty string, not a missing query."""
    return None if isinstance(value, str) and not value.strip() else value


OptionalQueryId = Annotated[int | None, BeforeValidator(_blank_query_id)]


def optional_int(value: str | int | None, *, field: str = "valor") -> int | None:
    """Convert empty HTML form values to None and validate integer identifiers."""
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    cleaned = str(value).strip()
    if cleaned in {"", "0", "none", "null"}:
        return None
    try:
        parsed = int(cleaned)
    except ValueError as exc:
        raise HTTPException(400, f"{field.capitalize()} inválido.") from exc
    return parsed if parsed > 0 else None


def optional_date(value: str | date | None, *, field: str = "fecha") -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise HTTPException(400, f"{field.capitalize()} inválida.") from exc


def clean_text(value: str | None, *, max_length: int = 500, required: bool = False, field: str = "campo") -> str:
    cleaned = (value or "").strip()
    if required and not cleaned:
        raise HTTPException(400, f"{field.capitalize()} es obligatorio.")
    return cleaned[:max_length]
