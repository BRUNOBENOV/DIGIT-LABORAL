"""Legacy DOS LSPRE notice records: read-only, auditable and non-operative.

Preserve original field semantics. FECSA1 is not assumed to be the actual
termination date; BORRAD=S is retained as an origin marker, not deleted.
No row implies legal notice delivery, receipt, compliance or payment.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .legacy_vacation_import import _employee_source_codes
from .models import Company, Employee, EmployeeEvent

SOURCE = "LSPRE"
EVENT_TYPE = "Preaviso histórico"
MARKER = "DIGIT_LSPRE_V1:"
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 5000
HEADERS = ("CODTRA", "CODEMP", "FECENT", "FECPRE", "FECSAL", "FECSA1",
           "DIAPRE", "BORRAD", "FECHAX", "HORASX", "USECOD")
REQUIRED = {"CODTRA", "CODEMP", "FECENT", "FECPRE", "FECSAL", "DIAPRE"}


def _code(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    text = str(value).strip()
    return text[:-2] if re.fullmatch(r"\d+\.0", text) else text


def _date(value: Any, epoch: datetime) -> str | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        if isinstance(value, datetime):
            dt = value.date()
        elif isinstance(value, date):
            dt = value
        elif isinstance(value, (int, float)):
            dt = from_excel(value, epoch=epoch)
            if isinstance(dt, datetime):
                dt = dt.date()
        else:
            dt = None
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    dt = datetime.strptime(str(value).strip(), fmt).date()
                    break
                except ValueError:
                    continue
        if isinstance(dt, date) and 1900 <= dt.year <= 2100:
            return dt.isoformat()
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def _days(value: Any) -> int | None:
    try:
        if value not in (None, "") and not isinstance(value, bool):
            days = int(value)
            if str(value).strip() in (str(days), str(float(days))) and 0 <= days <= 366:
                return days
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def parse_legacy_notice_workbook(content: bytes, filename: str) -> dict:
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("Subí la tabla LSPRE en un archivo Excel .xlsx.")
    if len(content) > MAX_BYTES:
        raise ValueError("El Excel supera 8 MB.")
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError("El archivo Excel no pudo abrirse.") from exc
    records: list[dict] = []
    try:
        sheet = workbook["lspre"] if "lspre" in workbook.sheetnames else workbook.active
        cursor = sheet.iter_rows(values_only=True)
        try:
            header_cells = next(cursor)
        except StopIteration:
            raise ValueError("El archivo está vacío.")
        headers = [str(cell or "").strip().upper() for cell in header_cells]
        if len([h for h in headers if h]) != len(set(h for h in headers if h)):
            raise ValueError("Hay columnas duplicadas en el Excel.")
        missing = REQUIRED.difference(headers)
        if missing:
            raise ValueError("Faltan campos LSPRE: " + ", ".join(sorted(missing)))
        for row_number, values in enumerate(cursor, start=2):
            if not any(value not in ("", None) for value in values):
                continue
            if len(records) >= MAX_ROWS:
                raise ValueError("El archivo supera el límite de 5.000 registros.")
            raw = {header: (values[i] if i < len(values) else None)
                   for i, header in enumerate(headers) if header}
            row: dict[str, Any] = {"source_row": row_number}
            row["company_code"] = _code(raw.get("CODEMP"))
            row["employee_code"] = _code(raw.get("CODTRA"))
            for source, target in (("FECENT", "admission_source"),
                                   ("FECPRE", "notice_date_source"),
                                   ("FECSAL", "departure_date_source"),
                                   ("FECSA1", "secondary_date_source"),
                                   ("FECHAX", "updated_source")):
                row[target] = _date(raw.get(source), workbook.epoch)
            row["days"] = _days(raw.get("DIAPRE"))
            row["deleted_source"] = str(raw.get("BORRAD") or "").strip().upper() == "S"
            row["deleted_marker_raw"] = _code(raw.get("BORRAD"))
            row["updated_time_source"] = str(raw.get("HORASX") or "").strip()[:30]
            row["operator_source"] = _code(raw.get("USECOD"))
            errors, warnings = [], []
            if not row["company_code"]:
                errors.append("Falta CODEMP.")
            if not row["employee_code"]:
                errors.append("Falta CODTRA.")
            for field in ("admission_source", "notice_date_source", "departure_date_source"):
                if row[field] is None:
                    errors.append("Fecha de origen no válida: " + field)
            if row["notice_date_source"] and row["admission_source"] and row["notice_date_source"] < row["admission_source"]:
                errors.append("FECPRE anterior a FECENT.")
            if row["departure_date_source"] and row["notice_date_source"] and row["departure_date_source"] < row["notice_date_source"]:
                errors.append("FECSAL anterior a FECPRE.")
            if row["days"] is None:
                warnings.append("DIAPRE no informado o no interpretable; no completar por cálculo.")
            elif row["days"] not in {15, 30, 45, 60, 90}:
                warnings.append("DIAPRE atípico; requiere revisión. No corregir automáticamente.")
            if row["secondary_date_source"] and row["departure_date_source"] and row["secondary_date_source"] != row["departure_date_source"]:
                warnings.append("FECSA1 distinto de FECSAL; significado por verificar.")
            if row["deleted_source"]:
                warnings.append("BORRAD=S: registro marcado como borrado en el archivo de respaldo.")
            row["errors"] = errors
            row["warnings"] = warnings
            signature = [
                row["company_code"], row["employee_code"], row["admission_source"] or "",
                row["notice_date_source"] or "", row["departure_date_source"] or "",
                row["secondary_date_source"] or "",
                str(row["days"]) if row["days"] is not None else "",
                row["deleted_marker_raw"],
            ]
            row["legacy_key"] = hashlib.sha256("|".join(signature).encode("utf-8")).hexdigest()[:24]
            row["source_hash"] = hashlib.sha256("|".join(signature + [
                row["updated_source"] or "", row["updated_time_source"],
                row["operator_source"],
            ]).encode("utf-8")).hexdigest()
            records.append(row)
    finally:
        workbook.close()
    if not records:
        raise ValueError("No hay registros LSPRE para analizar.")
    return {"filename": Path(filename).name[:180],
            "sha256": hashlib.sha256(content).hexdigest(),
            "source_rows": len(records), "rows": records}


def legacy_notice_data(event: EmployeeEvent) -> dict | None:
    detail = str(event.detail or "")
    if event.event_type != EVENT_TYPE or not detail.startswith(MARKER):
        return None
    try:
        payload = json.loads(detail[len(MARKER):])
        return payload if isinstance(payload, dict) and payload.get("source") == SOURCE else None
    except (ValueError, TypeError):
        return None


def legacy_notice_preview(db: Session, parsed: dict, allowed_company_ids: set[int]) -> dict:
    if not allowed_company_ids:
        raise ValueError("No se encontraron empresas autorizadas.")
    companies = list(db.scalars(select(Company).where(Company.id.in_(allowed_company_ids))))
    by_code: dict[str, list[Company]] = defaultdict(list)
    for company in companies:
        if company.legacy_code:
            by_code[_code(company.legacy_code)].append(company)
    chosen_company_ids = {company.id for company in companies if company.legacy_code}
    employees = list(db.scalars(select(Employee).where(
        Employee.company_id.in_(chosen_company_ids)
    ))) if chosen_company_ids else []
    by_source: dict[tuple[int, str], list[Employee]] = defaultdict(list)
    by_current: dict[tuple[int, str], list[Employee]] = defaultdict(list)
    for employee in employees:
        for code in _employee_source_codes(employee):
            by_source[(employee.company_id, code)].append(employee)
        if employee.employee_code is not None:
            by_current[(employee.company_id, str(employee.employee_code))].append(employee)
    previous_events = list(db.scalars(select(EmployeeEvent).where(
        EmployeeEvent.employee_id.in_([person.id for person in employees]),
        EmployeeEvent.event_type == EVENT_TYPE,
    ))) if employees else []
    existing: dict[str, list[dict]] = defaultdict(list)
    for event in previous_events:
        payload = legacy_notice_data(event)
        if payload and payload.get("legacy_key"):
            existing[payload["legacy_key"]].append(payload)
    # A shared historical identity with contradictory source contents is ambiguous
    # for ALL of its rows, including the first occurrence. Never import either.
    fingerprints_by_key: dict[str, set[str]] = defaultdict(set)
    for item in parsed["rows"]:
        fingerprints_by_key[item["legacy_key"]].add(item["source_hash"])
    conflicting_keys = {
        key for key, hashes in fingerprints_by_key.items() if len(hashes) > 1
    }
    seen: dict[str, str] = {}
    counters = Counter()
    rows = []
    for record in parsed["rows"]:
        row = dict(record)
        row["employee_id"], row["employee_name"], row["company_name"] = None, "", ""
        errors = list(row["errors"])
        key = row["legacy_key"]
        if key in conflicting_keys:
            row["state"] = "conflicto"
            errors.append("Misma clave histórica con datos contradictorios: excluir todas sus filas.")
        elif key in seen:
            row["state"] = "duplicado_archivo"
        else:
            seen[key] = row["source_hash"]
            matches = by_code.get(row["company_code"], [])
            if len(matches) != 1:
                errors.append("CODEMP sin coincidencia única en las empresas autorizadas.")
            else:
                company = matches[0]
                row["company_name"] = company.legal_name
                persons = by_source.get((company.id, row["employee_code"]), [])
                if not persons:
                    persons = by_current.get((company.id, row["employee_code"]), [])
                if len(persons) != 1:
                    errors.append("CODTRA sin legajo único vinculado: " +
                                  ("sin coincidencia" if not persons else "coincidencia ambigua"))
                else:
                    row["employee_id"] = persons[0].id
                    row["employee_name"] = persons[0].full_name
            old = existing.get(key, [])
            if old:
                row["state"] = "ya_importado" if (
                    len(old) == 1 and old[0].get("source_hash") == row["source_hash"]
                ) else "conflicto"
                if row["state"] == "conflicto":
                    errors.append("Ya existe una clave idéntica con distinto contenido.")
            elif errors:
                row["state"] = "rechazado"
            else:
                row["state"] = "listo"
        row["reason"] = " ".join(errors)
        counters[row["state"]] += 1
        rows.append(row)
    return {
        "rows": rows,
        "summary": {
            "source_rows": len(rows), "ready": counters["listo"],
            "already_imported": counters["ya_importado"],
            "rejected": counters["rechazado"], "conflicts": counters["conflicto"],
            "file_duplicates": counters["duplicado_archivo"],
            "source_deleted": sum(r["deleted_source"] for r in rows),
            "missing_days": sum(r["days"] is None for r in rows),
            "source_companies": len({r["company_code"] for r in rows}),
            "source_workers": len({(r["company_code"], r["employee_code"]) for r in rows}),
        },
    }


def make_notice_event(row: dict, filename: str, created_by: str) -> EmployeeEvent:
    if row.get("state") != "listo" or not row.get("employee_id"):
        raise ValueError("No se incorporan registros sin vínculo validado.")
    payload = {
        "source": SOURCE, "legacy_key": row["legacy_key"],
        "source_hash": row["source_hash"], "source_filename": Path(filename).name[:180],
        "source_row": row["source_row"], "company_code": row["company_code"],
        "employee_code": row["employee_code"], "admission_source": row["admission_source"],
        "notice_date_source": row["notice_date_source"],
        "departure_date_source": row["departure_date_source"],
        "secondary_date_source": row["secondary_date_source"],
        "days": row["days"], "deleted_source": row["deleted_source"],
        "deleted_marker_raw": row["deleted_marker_raw"],
        "updated_source": row["updated_source"],
        "updated_time_source": row["updated_time_source"],
        "operator_source": row["operator_source"], "warnings": row["warnings"],
        "legal_status": "Sin conciliación documental",
    }
    return EmployeeEvent(
        employee_id=row["employee_id"],
        event_type=EVENT_TYPE,
        title=("Preaviso histórico · borrado en origen" if row["deleted_source"]
               else "Preaviso histórico LSPRE"),
        detail=MARKER + json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")),
        effective_date=date.fromisoformat(row["notice_date_source"]),
        amount=None, created_by=created_by,
    )
