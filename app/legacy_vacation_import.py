"""Importación histórica no destructiva de vacaciones DOS/LSVAC.

Los movimientos se conservan como EmployeeEvent de solo lectura. No crean
Vacation, no conceden saldo, no modifican nóminas ni generan comunicaciones REOP.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Company, Employee, EmployeeEvent

SOURCE = "LSVAC"
EVENT_TYPE = "Vacaciones históricas"
MARKER = "DIGIT_LSVAC_V1:"
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10000
REQUIRED_COLUMNS = {
    "CODTRA", "CODEMP", "PERDES", "PERHAS", "INIVAC", "FINVAC",
    "FECREG", "DIACAU",
}
SOURCE_COLUMNS = (
    "CODTRA", "CODEMP", "TOTDIA", "FECENT", "FECACT", "PERDES",
    "PERHAS", "INIVAC", "FINVAC", "FECREG", "DIACAU",
    "SALMIN", "SALACT", "JORNAL", "VACACI", "DESIPS",
    "IPSXXX", "FECHAX", "HORASX", "USECOD",
)
IDENTITY_COLUMNS = ("CODEMP", "CODTRA", "PERDES", "PERHAS", "INIVAC", "FINVAC", "FECREG", "DIACAU")
_LEGACY_CODES = re.compile(r"Código\(s\) histórico\(s\) CODTRA:\s*([^\n.]+)", re.IGNORECASE)


def _code(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    raw = str(value).strip()
    if re.fullmatch(r"\d+\.0", raw):
        raw = raw[:-2]
    return raw


def _date(value: Any, epoch: datetime) -> str | None:
    if value in ("", None) or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (date, datetime)):
            output = value.date() if isinstance(value, datetime) else value
        elif isinstance(value, (int, float)):
            if value <= 0:
                return None
            converted = from_excel(value, epoch=epoch)
            output = converted.date() if isinstance(converted, datetime) else converted
        else:
            raw = str(value).strip()
            output = None
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
                try:
                    output = datetime.strptime(raw, fmt).date()
                    break
                except ValueError:
                    pass
        if not isinstance(output, date) or not 1900 <= output.year <= 2100:
            return None
        return output.isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _days(value: Any) -> int | None:
    try:
        number = Decimal(str(value))
        if number.is_finite() and number == number.to_integral_value() and 1 <= number <= 366:
            return int(number)
    except (TypeError, ValueError, InvalidOperation):
        pass
    return None


def _money(value: Any) -> str | None:
    if value in ("", None) or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0:
            return None
        return str(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except (TypeError, ValueError, InvalidOperation):
        return None


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def parse_legacy_vacation_workbook(content: bytes, filename: str) -> dict:
    """Read-only parser; never infers used leave days from calendar-day differences."""
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("Subí una copia Excel .xlsx de la tabla de vacaciones LSVAC.")
    if len(content) > MAX_BYTES:
        raise ValueError("El archivo supera el máximo permitido de 8 MB.")
    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    rows: list[dict] = []
    try:
        sheet = workbook["LSVAC"] if "LSVAC" in workbook.sheetnames else workbook.active
        iterator = sheet.iter_rows(values_only=True)
        try:
            source_headers = next(iterator)
        except StopIteration as exc:
            raise ValueError("El archivo de vacaciones está vacío.") from exc
        headers = [str(value or "").strip().upper() for value in source_headers]
        if len([h for h in headers if h]) != len(set(h for h in headers if h)):
            raise ValueError("El archivo tiene encabezados repetidos.")
        missing = sorted(REQUIRED_COLUMNS.difference(headers))
        if missing:
            raise ValueError("Faltan columnas LSVAC: " + ", ".join(missing))
        for rownum, values in enumerate(iterator, start=2):
            if not any(v not in ("", None) for v in values):
                continue
            if len(rows) >= MAX_ROWS:
                raise ValueError("El archivo supera el máximo de 10.000 movimientos.")
            raw = {headers[i]: values[i] if i < len(values) else None for i in range(len(headers))}
            record: dict[str, Any] = {"source_row": rownum}
            record["company_code"] = _code(raw.get("CODEMP"))
            record["employee_code"] = _code(raw.get("CODTRA"))
            for key, dest in (
                ("FECENT", "admission_date"), ("FECACT", "calculation_date"),
                ("PERDES", "period_from"), ("PERHAS", "period_to"),
                ("INIVAC", "vacation_start"), ("FINVAC", "vacation_end"),
                ("FECREG", "registered_on"), ("FECHAX", "updated_on"),
            ):
                record[dest] = _date(raw.get(key), workbook.epoch)
            record["days"] = _days(raw.get("DIACAU"))
            record["total_days"] = _money(raw.get("TOTDIA"))
            for key, dest in (
                ("SALMIN", "minimum_salary"), ("SALACT", "salary_snapshot"),
                ("JORNAL", "daily_wage"), ("VACACI", "vacation_amount"),
                ("DESIPS", "ips_discount"),
            ):
                record[dest] = _money(raw.get(key))
            record["ips_flag"] = str(raw.get("IPSXXX") or "").strip().upper()
            record["operator_code"] = _code(raw.get("USECOD"))
            record["errors"] = []
            for key, name in (("company_code", "Código empresa"), ("employee_code", "Código funcionario")):
                if not record[key]:
                    record["errors"].append(f"Falta {name.lower()}.")
            for key, name in (("period_from", "Inicio del período"), ("period_to", "Fin del período"),
                              ("vacation_start", "Inicio de vacaciones"), ("vacation_end", "Fin de vacaciones")):
                if not record[key]:
                    record["errors"].append(f"{name}: fecha no válida.")
            if record["days"] is None:
                record["errors"].append("Días de vacaciones no válidos.")
            if record["period_from"] and record["period_to"] and record["period_from"] > record["period_to"]:
                record["errors"].append("Período devengado invertido.")
            if record["vacation_start"] and record["vacation_end"] and record["vacation_start"] > record["vacation_end"]:
                record["errors"].append("Fechas de vacaciones invertidas.")
            key_parts = [
                record["company_code"], record["employee_code"],
                record["period_from"], record["period_to"],
                record["vacation_start"], record["vacation_end"],
                record["registered_on"], record["days"],
            ]
            record["legacy_key"] = _hash(key_parts)[:24]
            record["source_hash"] = _hash({key: record[key] for key in record if key not in {"errors", "source_row", "source_hash"}})
            rows.append(record)
    finally:
        workbook.close()
    if not rows:
        raise ValueError("No se encontraron movimientos de vacaciones.")
    return {
        "filename": Path(filename).name[:180],
        "source_rows": len(rows),
        "sha256": hashlib.sha256(content).hexdigest(),
        "rows": rows,
    }


def _employee_source_codes(employee: Employee) -> set[str]:
    found = _LEGACY_CODES.search(employee.notes or "")
    if not found:
        return set()
    return {code.strip() for code in found.group(1).split(",") if code.strip() and code.strip() != "No informado"}


def event_legacy_data(event: EmployeeEvent) -> dict | None:
    detail = str(event.detail or "")
    if not detail.startswith(MARKER):
        return None
    try:
        payload = json.loads(detail[len(MARKER):])
        return payload if isinstance(payload, dict) and payload.get("source") == SOURCE else None
    except (TypeError, ValueError):
        return None


def vacation_import_preview(db: Session, parsed: dict, allowed_company_ids: set[int]) -> dict:
    """Map CODEMP/CODTRA to already imported records, never use employee names."""
    if not allowed_company_ids:
        raise ValueError("No hay empresas autorizadas para esta importación.")
    companies = list(db.scalars(select(Company).where(Company.id.in_(allowed_company_ids))))
    by_code: dict[str, list[Company]] = defaultdict(list)
    for company in companies:
        if company.legacy_code:
            by_code[_code(company.legacy_code)].append(company)
    target_ids = {company.id for company in companies if company.legacy_code}
    employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(target_ids)))) if target_ids else []
    by_legacy: dict[tuple[int, str], list[Employee]] = defaultdict(list)
    by_number: dict[tuple[int, str], list[Employee]] = defaultdict(list)
    for employee in employees:
        for source_code in _employee_source_codes(employee):
            by_legacy[(employee.company_id, source_code)].append(employee)
        if employee.employee_code is not None:
            by_number[(employee.company_id, str(employee.employee_code))].append(employee)

    existing = list(db.scalars(select(EmployeeEvent).where(
        EmployeeEvent.employee_id.in_([employee.id for employee in employees]),
        EmployeeEvent.event_type == EVENT_TYPE,
    ))) if employees else []
    existing_by_key: dict[str, list[dict]] = defaultdict(list)
    for event in existing:
        details = event_legacy_data(event)
        if details and details.get("legacy_key"):
            existing_by_key[details["legacy_key"]].append(details)

    seen: set[str] = set()
    result: list[dict] = []
    counts = Counter()
    for source in parsed["rows"]:
        row = dict(source)
        row["employee_id"] = None
        row["employee_name"] = ""
        row["company_name"] = ""
        reasons: list[str] = list(row.get("errors") or [])
        source_key = row["legacy_key"]
        if source_key in seen:
            row["state"] = "duplicado_archivo"
            reasons.append("Movimiento idéntico repetido en el Excel.")
        else:
            seen.add(source_key)
            matches = by_code.get(row["company_code"], [])
            if len(matches) != 1:
                reasons.append("El código de empresa no corresponde a una única empresa del estudio.")
            else:
                company = matches[0]
                row["company_name"] = company.legal_name
                workers = by_legacy.get((company.id, row["employee_code"]), [])
                if not workers:
                    workers = by_number.get((company.id, row["employee_code"]), [])
                if len(workers) != 1:
                    reasons.append(
                        "El CODTRA no coincide con un único legajo importado."
                        if len(workers) == 0 else "CODTRA ambiguo: hay varios legajos coincidentes."
                    )
                else:
                    employee = workers[0]
                    row["employee_id"] = employee.id
                    row["employee_name"] = employee.full_name
            previous = existing_by_key.get(source_key, [])
            if previous:
                if len(previous) == 1 and previous[0].get("source_hash") == row["source_hash"]:
                    row["state"] = "ya_importado"
                else:
                    reasons.append("Ya existe el mismo movimiento con datos distintos; requiere revisión.")
                    row["state"] = "conflicto"
            elif reasons and row.get("state") != "duplicado_archivo":
                row["state"] = "rechazado"
            elif not reasons:
                row["state"] = "listo"
        row["reason"] = " ".join(reasons)
        counts[row["state"]] += 1
        result.append(row)
    return {
        "rows": result,
        "summary": {
            "source_rows": len(result),
            "ready": counts["listo"],
            "already_imported": counts["ya_importado"],
            "file_duplicates": counts["duplicado_archivo"],
            "rejected": counts["rechazado"],
            "conflicts": counts["conflicto"],
            "source_companies": len({r["company_code"] for r in result}),
            "source_employees": len({(r["company_code"], r["employee_code"]) for r in result}),
            "amount_missing": sum(row["vacation_amount"] is None for row in result),
        },
    }


def make_historical_vacation_event(row: dict, filename: str, created_by: str) -> EmployeeEvent:
    """Read-only history, not an available vacation balance or legal approval."""
    if row.get("state") != "listo" or not row.get("employee_id"):
        raise ValueError("No se pueden crear movimientos sin una vinculación verificada.")
    payload = {
        "source": SOURCE,
        "source_filename": Path(filename).name[:180],
        "legacy_key": row["legacy_key"],
        "source_hash": row["source_hash"],
        "source_row": row["source_row"],
        "company_code": row["company_code"],
        "employee_code": row["employee_code"],
        "period_from": row["period_from"],
        "period_to": row["period_to"],
        "vacation_start": row["vacation_start"],
        "vacation_end": row["vacation_end"],
        "registered_on": row["registered_on"],
        "days": row["days"],
        "salary_snapshot": row["salary_snapshot"],
        "minimum_salary": row["minimum_salary"],
        "daily_wage": row["daily_wage"],
        "vacation_amount": row["vacation_amount"],
        "ips_discount": row["ips_discount"],
        "ips_flag": row["ips_flag"],
        "total_days": row["total_days"],
        "admission_date": row["admission_date"],
        "calculation_date": row["calculation_date"],
        "operator_code": row["operator_code"],
    }
    amount = (
        int(Decimal(row["vacation_amount"]).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if row["vacation_amount"] is not None else None
    )
    return EmployeeEvent(
        employee_id=row["employee_id"],
        event_type=EVENT_TYPE,
        title=f"Vacaciones históricas {row['vacation_start']} · LSVAC",
        detail=MARKER + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        effective_date=date.fromisoformat(row["vacation_start"]),
        amount=amount,
        created_by=created_by,
    )
