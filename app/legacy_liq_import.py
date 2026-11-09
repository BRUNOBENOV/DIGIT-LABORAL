"""Importación auditada de liquidaciones históricas DOS/LSLIQ.

Se vincula a los legajos existentes por CODEMP/CODTRA. No crea egresos,
cálculos, liquidaciones operativas, salarios, recibos, pagos ni obligaciones
REOP/REI. Los importes y fechas de origen se preservan íntegramente.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Company, Employee, EmployeeEvent
from .legacy_vacation_import import _employee_source_codes

SOURCE = "LSLIQ"
EVENT_TYPE = "Liquidación final histórica"
MARKER = "DIGIT_LSLIQ_V1:"
MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 20_000
SOURCE_FIELDS = (
    "CODTRA", "CODEMP", "FECENT", "FECSAL", "FECPRE", "RENDES", "CONTES",
    "IPSXXX", "ANOXXX", "MESXXX", "DIAXXX", "SALACT", "TOTSAL", "SALPRO",
    "DTANOX", "DIAAGU", "JORAGU", "AGUINA", "DIACAU", "JORCAU", "CAUSAD",
    "DIAPRO", "JORPRO", "PROPOR", "DIAPRE", "JORPRE", "PREAVI", "DIAIND",
    "JORIND", "INDEMN", "MOTSAL", "FECHAX", "HORASX", "USECOD",
)
REQUIRED = {"CODEMP", "CODTRA", "FECENT", "FECSAL", "AGUINA", "INDEMN"}
AMOUNTS = ("SALACT", "TOTSAL", "SALPRO", "JORAGU", "AGUINA", "JORCAU",
           "CAUSAD", "JORPRO", "PROPOR", "JORPRE", "PREAVI", "JORIND", "INDEMN")


def _string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return "S" if value else "N"
    raw = str(value).strip()
    return raw[:300]


def _code(value: Any) -> str:
    raw = _string(value)
    return raw[:-2] if re.fullmatch(r"\d+\.0", raw) else raw


def _date_from_source(value: Any, epoch: datetime) -> str | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        if isinstance(value, datetime):
            resolved = value.date()
        elif isinstance(value, date):
            resolved = value
        elif isinstance(value, (int, float, Decimal)):
            if Decimal(str(value)) <= 0:
                return None
            resolved = from_excel(value, epoch=epoch)
            if isinstance(resolved, datetime):
                resolved = resolved.date()
        else:
            resolved = None
            raw = _string(value)
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    resolved = datetime.strptime(raw, fmt).date()
                    break
                except ValueError:
                    continue
        if isinstance(resolved, date) and 1900 <= resolved.year <= 2100:
            return resolved.isoformat()
    except (OverflowError, ValueError, TypeError, InvalidOperation):
        return None
    return None


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def parse_legacy_liq_workbook(content: bytes, filename: str) -> dict:
    """Preserve 34 source values; reject invalid exit/admission dates."""
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("La base de liquidaciones debe tener formato .xlsx.")
    if len(content) > MAX_BYTES:
        raise ValueError("El Excel supera 10 MB.")
    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    records = []
    try:
        sheet = workbook["LSLIQ"] if "LSLIQ" in workbook.sheetnames else workbook.active
        stream = sheet.iter_rows(values_only=True)
        try:
            header = next(stream)
        except StopIteration as exc:
            raise ValueError("La planilla de liquidaciones está vacía.") from exc
        headers = [_string(v).upper() for v in header]
        nonempty = [h for h in headers if h]
        if len(nonempty) != len(set(nonempty)):
            raise ValueError("El archivo contiene encabezados repetidos.")
        missing = sorted(REQUIRED.difference(headers))
        if missing:
            raise ValueError("Columnas LSLIQ faltantes: " + ", ".join(missing))
        indexes = {field: headers.index(field) for field in SOURCE_FIELDS if field in headers}
        for source_row, values in enumerate(stream, 2):
            if not any(v not in (None, "") for v in values):
                continue
            if len(records) >= MAX_ROWS:
                raise ValueError("El archivo supera los 20.000 movimientos admitidos.")
            raw = {
                field: _string(values[indexes[field]])
                if field in indexes and indexes[field] < len(values) else ""
                for field in SOURCE_FIELDS
            }
            admission = _date_from_source(
                values[indexes["FECENT"]] if indexes["FECENT"] < len(values) else None, workbook.epoch
            )
            departure = _date_from_source(
                values[indexes["FECSAL"]] if indexes["FECSAL"] < len(values) else None, workbook.epoch
            )
            notice = _date_from_source(
                values[indexes["FECPRE"]] if "FECPRE" in indexes and indexes["FECPRE"] < len(values) else None, workbook.epoch
            )
            errors, warnings = [], []
            company_code, employee_code = _code(raw["CODEMP"]), _code(raw["CODTRA"])
            if not company_code or not employee_code:
                errors.append("Falta CODEMP o CODTRA.")
            if not admission:
                errors.append("FECENT inválida o fuera del rango 1900–2100.")
            if not departure:
                errors.append("FECSAL inválida o fuera del rango 1900–2100.")
            if admission and departure and admission > departure:
                errors.append("Fecha de egreso anterior a la de ingreso.")
            if raw.get("FECPRE") and not notice:
                warnings.append("FECPRE inválida; verificar preaviso.")
            if not raw.get("MOTSAL"):
                warnings.append("MOTSAL no indica el motivo de egreso.")
            for field in AMOUNTS:
                value = raw[field]
                if not value:
                    continue
                try:
                    amount = Decimal(value)
                    if not amount.is_finite():
                        errors.append(f"{field}: importe no finito.")
                    elif amount < 0:
                        warnings.append(f"{field}: importe negativo en origen; requiere revisión.")
                except InvalidOperation:
                    errors.append(f"{field}: importe ilegible.")
            key = _hash([company_code, employee_code, admission, departure])[:32]
            records.append({
                "source_row": source_row, "company_code": company_code,
                "employee_code": employee_code, "admission": admission,
                "departure": departure, "notice": notice,
                "legacy_key": key, "source_hash": _hash(raw),
                "values": raw, "errors": errors, "warnings": warnings,
            })
    finally:
        workbook.close()
    if not records:
        raise ValueError("No se detectaron liquidaciones históricas.")
    return {
        "filename": Path(filename).name[:180], "source_rows": len(records),
        "sha256": hashlib.sha256(content).hexdigest(), "rows": records,
    }


def liq_event_data(event_or_detail: EmployeeEvent | str) -> dict | None:
    detail = (event_or_detail.detail if isinstance(event_or_detail, EmployeeEvent)
              else str(event_or_detail or ""))
    if not detail.startswith(MARKER):
        return None
    try:
        value = json.loads(detail[len(MARKER):])
        return value if isinstance(value, dict) and value.get("source") == SOURCE else None
    except (TypeError, ValueError):
        return None


def preview_liq_import(db: Session, parsed: dict, allowed_company_ids: set[int]) -> dict:
    """Only existing companies/legajos within this studio can be matched."""
    if not allowed_company_ids:
        raise ValueError("No hay empresas autorizadas en tu estudio.")
    companies = list(db.scalars(select(Company).where(Company.id.in_(allowed_company_ids))))
    by_company = defaultdict(list)
    for company in companies:
        code = _code(company.legacy_code) if company.legacy_code else (
            str(company.company_code) if company.company_code is not None else ""
        )
        if code:
            by_company[code].append(company)
    ids = [company.id for company in companies]
    employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(ids))))
    by_legacy = defaultdict(list)
    by_number = defaultdict(list)
    for employee in employees:
        for code in _employee_source_codes(employee):
            by_legacy[(employee.company_id, code)].append(employee)
        if employee.employee_code is not None:
            by_number[(employee.company_id, str(employee.employee_code))].append(employee)

    existing = defaultdict(set)
    if employees:
        for (detail,) in db.execute(select(EmployeeEvent.detail).where(
            EmployeeEvent.employee_id.in_([employee.id for employee in employees]),
            EmployeeEvent.event_type == EVENT_TYPE,
        )):
            old = liq_event_data(detail)
            if old and old.get("legacy_key"):
                existing[old["legacy_key"]].add(old.get("source_hash", ""))
    keys = Counter(row["legacy_key"] for row in parsed["rows"])
    counts = Counter()
    mapping = {}
    states = {}
    ready_sample, issue_sample = [], []
    for row in parsed["rows"]:
        reasons = list(row["errors"])
        employee_id = None
        company_name, employee_name = "", ""
        company_matches = by_company.get(row["company_code"], [])
        if len(company_matches) != 1:
            reasons.append("Empresa CODEMP sin coincidencia única en el estudio.")
        else:
            company = company_matches[0]
            company_name = company.legal_name
            workers = by_legacy.get((company.id, row["employee_code"]), [])
            if not workers:
                workers = by_number.get((company.id, row["employee_code"]), [])
            if len(workers) != 1:
                reasons.append("CODTRA no coincide con un único legajo importado.")
            else:
                employee_id, employee_name = workers[0].id, workers[0].full_name
        hashes = existing.get(row["legacy_key"], set())
        if keys[row["legacy_key"]] > 1:
            state = "conflicto"
            reasons.append("Más de una liquidación para el mismo legajo e ingreso/egreso.")
        elif hashes:
            state = "ya_importado" if hashes == {row["source_hash"]} else "conflicto"
            if state == "conflicto":
                reasons.append("Una liquidación anterior existe con valores diferentes.")
        elif reasons:
            state = "rechazado"
        else:
            state = "listo"
        states[row["legacy_key"]] = state
        counts[state] += 1
        if row["warnings"]:
            counts["advertencias"] += 1
        if state in {"listo", "ya_importado"} and employee_id:
            mapping[row["legacy_key"]] = employee_id
        sample = {
            "source_row": row["source_row"], "company_code": row["company_code"],
            "employee_code": row["employee_code"], "employee_id": employee_id,
            "company_name": company_name, "employee_name": employee_name,
            "admission": row["admission"], "departure": row["departure"],
            "aguinaldo": row["values"]["AGUINA"],
            "indemnizacion": row["values"]["INDEMN"],
            "state": state, "reason": " ".join(reasons),
            "warnings": " ".join(row["warnings"]),
        }
        if state == "listo" and len(ready_sample) < 30:
            ready_sample.append(sample)
        elif state != "listo" and len(issue_sample) < 55:
            issue_sample.append(sample)
    return {
        "summary": {
            "source_rows": len(parsed["rows"]), "ready": counts["listo"],
            "already_imported": counts["ya_importado"],
            "rejected": counts["rechazado"], "conflicts": counts["conflicto"],
            "warnings": counts["advertencias"],
        },
        "employee_mapping": mapping, "states": states,
        "sample_ready": ready_sample, "sample_issues": issue_sample,
    }


def make_liq_event(row: dict, employee_id: int, filename: str, author: str) -> EmployeeEvent:
    if not row.get("departure"):
        raise ValueError("La fecha de egreso histórica no puede quedar vacía.")
    payload = {
        "source": SOURCE, "filename": filename, "source_row": row["source_row"],
        "company_code": row["company_code"], "employee_code": row["employee_code"],
        "admission": row["admission"], "departure": row["departure"],
        "notice": row["notice"], "legacy_key": row["legacy_key"],
        "source_hash": row["source_hash"], "values": row["values"],
        "warnings": row["warnings"], "operational": False,
    }
    return EmployeeEvent(
        employee_id=employee_id, event_type=EVENT_TYPE,
        title=f"Liquidación final histórica {row['departure']} · LIQ",
        effective_date=date.fromisoformat(row["departure"]),
        amount=None,  # No existe comprobante de pago ni total final verificado.
        detail=MARKER + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        created_by=author,
    )


def historical_liq_detail(event: EmployeeEvent) -> str | None:
    """Human-readable detail for the original employee dossier timeline."""
    record = liq_event_data(event)
    if record is None:
        return None
    values = record.get("values") or {}
    concepts = [
        (key, name) for key, name in (
            ("AGUINA", "Aguinaldo"), ("CAUSAD", "Vacaciones causadas"),
            ("PROPOR", "Vacaciones proporcionales"), ("PREAVI", "Preaviso"),
            ("INDEMN", "Indemnización"),
        )
    ]
    pieces = "; ".join(f"{label}: {values.get(field) or 'sin dato'} Gs."
                       for field, label in concepts)
    warnings = record.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [str(warnings)]
    warning_detail = (
        " ADVERTENCIAS DE ORIGEN: " + "; ".join(str(value) for value in warnings if value) + ". "
        "Requiere revisión profesional antes de uso jurídico o contable."
        if warnings else ""
    )
    return (
        f"LSLIQ · Ingreso: {record.get('admission') or '—'}; "
        f"egreso: {record.get('departure') or '—'}; "
        f"motivo original: {values.get('MOTSAL') or 'no informado'}. "
        f"{pieces}. Fuente: {record.get('filename') or 'LIQ'}, "
        f"fila {record.get('source_row') or '—'}. "
        "Antecedente histórico no conciliado; no acredita pago ni validez jurídica."
        f"{warning_detail}"
    )
