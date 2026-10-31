"""Bounded choices for the reusable company and employee comboboxes."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from jinja2 import pass_context


SEED_LIMIT = 10


def _positive_ids(values: Iterable[Any]) -> set[int]:
    result = set()
    for value in values:
        if hasattr(value, "id"):
            value = value.id
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if 0 < number <= 2_147_483_647:
            result.add(number)
    return result


def seed_choices(db, query, model, *, request=None, selected_ids=()):
    """Keep only a small seed and explicitly selected, already-scoped records."""
    selected_ids = list(selected_ids)
    if request is not None:
        name = "company_id" if model.__tablename__ == "companies" else "employee_id"
        selected_ids.extend(request.query_params.getlist(name))
    rows = list(db.scalars(query.limit(SEED_LIMIT)))
    missing = _positive_ids(selected_ids) - {row.id for row in rows}
    if missing:
        rows.extend(db.scalars(query.where(model.id.in_(missing)).limit(len(missing))))
    return rows


@pass_context
def entity_choices(context, rows):
    """Bound option loops even when a page also needs the full data for its content."""
    rows = list(rows)
    if not rows:
        return []
    company = rows[0].__tablename__ == "companies"
    kind = "company" if company else "employee"
    values = [context.get(key) for key in (f"selected_{kind}", f"selected_{kind}_id", f"{kind}_id", f"selected_{kind}_obj")]
    if not company:
        values.append(context.get("employee_filter"))
    request = context.get("request")
    if request:
        values.extend(request.query_params.getlist(f"{kind}_id"))
    for key in ("edit_record", "editing", "editing_contract", "selected_calculation"):
        record = context.get(key)
        if record:
            values.append(getattr(record, f"{kind}_id", None))
    values.append((context.get("editing_payload") or {}).get(f"{kind}_id"))
    wanted = _positive_ids(values)
    seed = rows[:SEED_LIMIT]
    present = {row.id for row in seed}
    return seed + [row for row in rows[SEED_LIMIT:] if row.id in wanted - present]
