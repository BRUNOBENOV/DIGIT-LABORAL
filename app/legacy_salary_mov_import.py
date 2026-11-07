"""Importación no destructiva del archivo DOS / BASE DE DATOS MOV.csv.xlsx.

Una fila MOV es un antecedente salarial, no un recibo, nómina aprobada,
remuneración mensual convenida ni comprobante IPS/REOP/REI.
"""
from __future__ import annotations

import calendar
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Company, Employee, EmployeeEvent

EVENT_TYPE = "Salario histórico MOV"
MARKER = "DIGIT_MOV_V1:"
MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 100_000
FIELDS = (
    "CODTRA", "CODEMP", "PAGDEL", "PAGALX", "MESDEX", "ANOXXX",
    "DIATRA", "DIATRA1", "JORNAL", "SALACT", "SALMIN", "SALARI",
    "SALARI1", "HOREXT", "HOR030", "HOR050", "HOR080", "HOR100",
    "HOR130", "COMREM", "DESIPS", "PATIPS", "DESOTR", "CANHIJ",
    "BONIFI", "MONEDA", "FECHAX", "HORASX", "USECOD",
)
REQUIRED = {"CODTRA", "CODEMP", "MESDEX", "PAGDEL", "PAGALX", "SALARI"}
LEGACY_CODES = re.compile(r"Código\(s\) histórico\(s\) CODTRA:\s*([^\n.]+)", re.IGNORECASE)


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return format(Decimal(str(value)), "f")
    return str(value).strip()


def _code(value: object) -> str:
    raw = _text(value).strip()
    return raw[:-2] if re.fullmatch(r"\d+\.0", raw) else raw


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _period(value: str) -> str:
    value = _code(value)
    if not re.fullmatch(r"(19|20)\d{4}", value):
        return ""
    year, month = int(value[:4]), int(value[4:6])
    return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else ""


def _record(raw: dict[str, str], row_number: int) -> dict:
    code_company = _code(raw.get("CODEMP"))
    code_employee = _code(raw.get("CODTRA"))
    period = _period(_text(raw.get("MESDEX")))
    start, end = _text(raw.get("PAGDEL")), _text(raw.get("PAGALX"))
    key = _digest((code_company, code_employee, period, start, end))[:32]
    errors = []
    warnings = []
    if not code_company or not code_employee:
        errors.append("Falta CODEMP o CODTRA.")
    if not period:
        errors.append("MESDEX inválido.")
    if not start or not end:
        errors.append("Falta PAGDEL o PAGALX.")
    else:
        try:
            beginning, ending = int(Decimal(start)), int(Decimal(end))
            if beginning < 1 or ending < beginning or ending > 31:
                warnings.append("Rango PAGDEL/PAGALX atípico; verificar su significado.")
            elif period and ending > calendar.monthrange(int(period[:4]), int(period[5:7]))[1]:
                warnings.append("PAGALX excede los días calendario; puede responder al mes comercial de 30 días.")
        except (InvalidOperation, ValueError, OverflowError):
            warnings.append("Rango PAGDEL/PAGALX no numérico.")
    for monetary in ("SALARI", "SALARI1", "SALACT", "JORNAL", "DESIPS", "PATIPS"):
        value = raw.get(monetary) or ""
        if value:
            try:
                number = Decimal(value)
                if not number.is_finite() or number < 0:
                    errors.append(f"{monetary}: importe inválido.")
            except (InvalidOperation, ValueError):
                errors.append(f"{monetary}: importe no numérico.")
    return {
        "source_row": row_number, "company_code": code_company,
        "employee_code": code_employee, "period": period,
        "legacy_key": key, "source_hash": _digest(raw),
        "raw": raw, "errors": errors, "warnings": warnings,
    }


def parse_legacy_mov_workbook(content: bytes, filename: str) -> dict:
    """Parse with streaming Excel; preserve original source columns and precision."""
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("El archivo MOV debe ser .xlsx.")
    if len(content) > MAX_BYTES:
        raise ValueError("El archivo supera 10 MB.")
    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    records = []
    try:
        sheet = workbook.active
        iterator = sheet.iter_rows(values_only=True)
        try:
            first = next(iterator)
        except StopIteration as exc:
            raise ValueError("El archivo está vacío.") from exc
        headers = [_text(h).strip().upper() for h in first]
        if len([h for h in headers if h]) != len({h for h in headers if h}):
            raise ValueError("Se encontraron encabezados duplicados.")
        missing = sorted(REQUIRED.difference(headers))
        if missing:
            raise ValueError("Faltan columnas obligatorias del archivo MOV: " + ", ".join(missing))
        indexes = {name: headers.index(name) for name in FIELDS if name in headers}
        for row_number, values in enumerate(iterator, 2):
            if not any(v not in ("", None) for v in values):
                continue
            if len(records) >= MAX_ROWS:
                raise ValueError("La base supera los 100.000 movimientos admitidos.")
            data = {
                name: _text(values[indexes[name]]) if name in indexes and indexes[name] < len(values) else ""
                for name in FIELDS
            }
            records.append(_record(data, row_number))
    finally:
        workbook.close()
    if not records:
        raise ValueError("No se encontraron movimientos salariales.")
    return {
        "filename": Path(filename).name[:180],
        "sha256": hashlib.sha256(content).hexdigest(),
        "source_rows": len(records),
        "rows": records,
    }


def event_data(detail: str) -> dict | None:
    if not (detail or "").startswith(MARKER):
        return None
    try:
        value = json.loads(detail[len(MARKER):])
        return value if isinstance(value, dict) and value.get("source") == "MOV" else None
    except (ValueError, TypeError):
        return None


def _legacy_employee_codes(employee: Employee) -> set[str]:
    match = LEGACY_CODES.search(employee.notes or "")
    if not match:
        return set()
    return {part.strip() for part in match.group(1).split(",") if part.strip()}


def preview_mov_import(db: Session, parsed: dict, allowed_company_ids: set[int]) -> dict:
    """Join by company legacy code and employee's imported CODTRA, never by name."""
    if not allowed_company_ids:
        raise ValueError("No hay empresas habilitadas para esta importación.")
    companies = list(db.scalars(select(Company).where(Company.id.in_(allowed_company_ids))))
    companies_by_code = defaultdict(list)
    for company in companies:
        if company.legacy_code:
            companies_by_code[_code(company.legacy_code)].append(company)
    company_ids = {company.id for company in companies if company.legacy_code}
    employees = list(db.scalars(
        select(Employee).where(Employee.company_id.in_(company_ids))
    )) if company_ids else []
    employee_by_code = defaultdict(list)
    employee_by_number = defaultdict(list)
    for employee in employees:
        for code in _legacy_employee_codes(employee):
            employee_by_code[(employee.company_id, code)].append(employee)
        if employee.employee_code is not None:
            employee_by_number[(employee.company_id, str(employee.employee_code))].append(employee)

    previous_records: dict[str, set[str]] = defaultdict(set)
    if employees:
        employee_ids = [employee.id for employee in employees]
        for (detail,) in db.execute(
            select(EmployeeEvent.detail).where(
                EmployeeEvent.employee_id.in_(employee_ids),
                EmployeeEvent.event_type == EVENT_TYPE,
            )
        ):
            source = event_data(detail)
            if source and source.get("legacy_key"):
                previous_records[source["legacy_key"]].add(source.get("source_hash", ""))

    key_counts = Counter(r["legacy_key"] for r in parsed["rows"])
    summary = Counter()
    ready_sample, issue_sample = [], []
    preview_mapping = {}
    for row in parsed["rows"]:
        reason = list(row["errors"])
        company_name, employee_name, employee_id = "", "", None
        company_matches = companies_by_code.get(row["company_code"], [])
        if len(company_matches) != 1:
            reason.append("Código CODEMP inexistente o ambiguo en este estudio.")
        else:
            company = company_matches[0]
            company_name = company.legal_name
            workers = employee_by_code.get((company.id, row["employee_code"]), [])
            if not workers:
                workers = employee_by_number.get((company.id, row["employee_code"]), [])
            if len(workers) != 1:
                reason.append("CODTRA sin legajo único para esa empresa.")
            else:
                employee_id, employee_name = workers[0].id, workers[0].full_name
        old_hashes = previous_records.get(row["legacy_key"], set())
        if key_counts[row["legacy_key"]] > 1:
            state = "conflicto"
            reason.append("Más de una fila con idénticos códigos, mes y rango; revisar versiones.")
        elif old_hashes:
            state = "ya_importado" if old_hashes == {row["source_hash"]} else "conflicto"
            if state == "conflicto":
                reason.append("Movimiento existente con distinto contenido; no se sobrescribe.")
        elif reason:
            state = "rechazado"
        else:
            state = "listo"
        summary[state] += 1
        if row["warnings"]:
            summary["con_advertencias"] += 1
        if state in ("listo", "ya_importado") and employee_id:
            preview_mapping[row["legacy_key"]] = employee_id
        sample = {
            "source_row": row["source_row"], "company_code": row["company_code"],
            "employee_code": row["employee_code"], "period": row["period"],
            "company_name": company_name, "employee_name": employee_name,
            "employee_id": employee_id, "state": state,
            "salary": row["raw"]["SALARI"],
            "reason": " ".join(reason), "warnings": " ".join(row["warnings"]),
            "legacy_key": row["legacy_key"],
        }
        if state == "listo" and len(ready_sample) < 35:
            ready_sample.append(sample)
        elif state != "listo" and len(issue_sample) < 60:
            issue_sample.append(sample)
    return {
        "summary": {
            "source_rows": len(parsed["rows"]),
            "ready": summary["listo"],
            "already_imported": summary["ya_importado"],
            "rejected": summary["rechazado"],
            "conflicts": summary["conflicto"],
            "warnings": summary["con_advertencias"],
            "source_companies": len({row["company_code"] for row in parsed["rows"]}),
            "source_employees": len({(row["company_code"], row["employee_code"]) for row in parsed["rows"]}),
        },
        "sample_ready": ready_sample, "sample_issues": issue_sample,
        "employee_mapping": preview_mapping,
        "states": {
            row["legacy_key"]: (
                "conflicto" if key_counts[row["legacy_key"]] > 1
                else "ya_importado" if previous_records.get(row["legacy_key"]) == {row["source_hash"]}
                else "conflicto" if previous_records.get(row["legacy_key"])
                else "rechazado" if row["errors"] or row["legacy_key"] not in preview_mapping
                else "listo"
            )
            for row in parsed["rows"]
        },
    }


def make_mov_event(row: dict, employee_id: int, filename: str, created_by: str) -> EmployeeEvent:
    """Store original row only in read-only history; never touch operational salary."""
    raw = row["raw"]
    raw_amount = raw.get("SALARI") or ""
    amount = None
    if raw_amount:
        parsed_amount = Decimal(raw_amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if 0 <= parsed_amount <= 2_147_483_647:
            amount = int(parsed_amount)
    payload = {
        "source": "MOV", "filename": filename, "source_row": row["source_row"],
        "legacy_key": row["legacy_key"], "source_hash": row["source_hash"],
        "company_code": row["company_code"], "employee_code": row["employee_code"],
        "period": row["period"], "warnings": row["warnings"], "values": raw,
        "operational": False,
    }
    return EmployeeEvent(
        employee_id=employee_id, event_type=EVENT_TYPE,
        title=f"Remuneración histórica {row['period']} · MOV",
        effective_date=date.fromisoformat(row["period"] + "-01"),
        amount=amount,
        detail=MARKER + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        created_by=created_by,
    )


def historical_mov_detail(event: EmployeeEvent) -> str | None:
    """Readable salary-source summary for the EXISTING employee timeline."""
    record = event_data(event.detail)
    if record is None:
        return None
    values = record.get("values") or {}
    reference = record.get("period") or event.effective_date.strftime("%Y-%m")
    text = (
        f"MOV {reference} · SALARI registrado: {values.get('SALARI') or 'no informado'} Gs. "
        f"DESIPS original: {values.get('DESIPS') or 'no informado'} Gs. "
        f"Días registrados DIATRA: {values.get('DIATRA') or 'sin dato'}. "
        f"Fuente: {record.get('filename') or 'MOV'}, fila {record.get('source_row') or '—'}. "
        "Dato histórico sin conciliación; no es recibo ni pago comprobado."
    )
    return text
