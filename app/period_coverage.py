"""Annual payroll-period coverage and conservative history reuse helpers.

This module deliberately diagnoses the presence/consistency of payroll records.
It does not determine which earning concepts are legally computable for aguinaldo.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any, Mapping
from zoneinfo import ZoneInfo

MONTHS_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
TZ_PARAGUAY = ZoneInfo("America/Asuncion")


def current_paraguay_date() -> date:
    """Return the current date in Paraguay, regardless of the host timezone."""
    from datetime import datetime

    return datetime.now(TZ_PARAGUAY).date()


def expected_months(
    year: int,
    admission_date: date,
    termination_date: date | None = None,
    *,
    today: date | None = None,
) -> list[str]:
    """Periods overlapping the employment relationship, up to the current month.

    A period is expected when at least one day of the month overlaps the
    employment relationship. This is a data-coverage rule, not a legal
    prorating rule for remuneration, vacation, or aguinaldo.
    """
    today = today or current_paraguay_date()
    if year < admission_date.year or year > today.year:
        return []
    last_month = today.month if year == today.year else 12
    expected: list[str] = []
    for month in range(1, last_month + 1):
        month_start = date(year, month, 1)
        month_end = date(year, month, monthrange(year, month)[1])
        if month_end < admission_date:
            continue
        if termination_date and month_start > termination_date:
            continue
        expected.append(f"{year:04d}-{month:02d}")
    return expected


def build_annual_coverage(
    *,
    year: int,
    admission_date: date,
    termination_date: date | None,
    payroll_by_period: Mapping[str, Mapping[str, Any]],
    saved_salary_periods: set[str] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Describe evidence for each expected month and a conservative gross sum.

    Only internally consistent payroll rows with status 'Cerrada' contribute
    to suggested_total. Even that amount is only the sum of recorded gross
    payrolls; the caller must not label it as a legally validated aguinaldo base.
    """
    saved_salary_periods = saved_salary_periods or set()
    periods = expected_months(year, admission_date, termination_date, today=today)
    rows: list[dict[str, Any]] = []
    suggested_total = 0
    closed_count = 0
    open_count = 0
    missing_count = 0
    inconsistent_count = 0
    salary_history: list[dict[str, Any]] = []

    for period in periods:
        month = int(period[-2:])
        record = payroll_by_period.get(period)
        row: dict[str, Any] = {
            "period": period,
            "month_label": MONTHS_ES[month - 1].capitalize(),
            "status": "",
            "status_key": "",
            "gross": None,
            "base_salary": None,
            "payroll_status": "",
            "has_saved_calculation": period in saved_salary_periods,
            "included_in_suggestion": False,
            "note": "",
        }
        if record:
            row["payroll_status"] = str(record.get("status") or "Borrador")
            row["base_salary"] = int(record.get("base_salary") or 0)
            if row["base_salary"] > 0:
                salary_history.append({"period": period, "base_salary": row["base_salary"]})
            if not record.get("amounts_consistent", False):
                row.update(
                    status="Importes inconsistentes",
                    status_key="inconsistent",
                    note="La suma de conceptos no coincide con el bruto guardado; se excluye de la suma sugerida.",
                )
                inconsistent_count += 1
            elif row["payroll_status"] == "Cerrada":
                row.update(
                    status="Nómina cerrada",
                    status_key="closed",
                    gross=int(record.get("gross") or 0),
                    included_in_suggestion=True,
                    note="Incluida en la suma bruta registrada; revisar la procedencia legal de cada concepto.",
                )
                suggested_total += row["gross"]
                closed_count += 1
            else:
                row.update(
                    status="Nómina abierta",
                    status_key="open",
                    gross=int(record.get("gross") or 0),
                    note="Existe una nómina no cerrada; requiere revisión y no se incluye en la suma sugerida.",
                )
                open_count += 1
        elif period in saved_salary_periods:
            row.update(
                status="Solo cálculo guardado",
                status_key="calculation",
                note="Existe un cálculo de salario, pero no sustituye una nómina mensual.",
            )
            missing_count += 1
        else:
            row.update(
                status="Sin registro",
                status_key="missing",
                note="No se encontró una nómina mensual ni un cálculo salarial guardado para este período.",
            )
            missing_count += 1
        rows.append(row)

    distinct_salaries = sorted({item["base_salary"] for item in salary_history})
    changes = len(distinct_salaries) > 1
    all_closed = bool(rows) and closed_count == len(rows)
    if year == today.year:
        cutoff = MONTHS_ES[today.month - 1]
        if all_closed:
            coverage_note = (
                f"Los meses transcurridos hasta {cutoff} tienen nómina cerrada y consistente. "
                "Este resultado no representa el cierre anual; los meses futuros se incorporarán cuando corresponda."
            )
        else:
            coverage_note = (
                f"La cobertura hasta {cutoff} está incompleta o requiere revisión. "
                "Los meses futuros no se consideran faltantes todavía."
            )
    elif all_closed:
        coverage_note = "Cobertura documental anual completa: todos los meses esperados tienen nómina cerrada y consistente."
    else:
        coverage_note = "El ejercicio cerrado tiene períodos faltantes o pendientes de revisión."
    return {
        "year": year,
        "periods": rows,
        "expected_count": len(rows),
        "closed_count": closed_count,
        "open_count": open_count,
        "missing_count": missing_count,
        "inconsistent_count": inconsistent_count,
        "suggested_total": suggested_total,
        "is_complete": all_closed,
        "salary_changes_detected": changes,
        "salary_history": salary_history,
        "salary_values": distinct_salaries,
        "coverage_note": coverage_note,
        "legal_note": (
            "La suma propuesta es el bruto registrado en nóminas cerradas. No constituye automáticamente la base legal "
            "del aguinaldo: revisá conceptos computables, ajustes, anticipos y reglas aplicables antes de aprobar."
        ),
    }
