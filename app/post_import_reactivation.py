"""Safe, one-off correction of statuses set by the historical employee import.

This module deliberately never updates admission dates, salaries, payroll,
historical EmployeeEvent records, or source-import provenance.
"""
from __future__ import annotations

import csv
import io
import math
import re
from datetime import UTC, date, datetime
from zipfile import BadZipFile

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditLog, Company, Employee, EmployeeEvent, EmployeeExit, FinalSettlement

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_IDENTIFIERS = 15_000
AUDIT_MESSAGE = "Corrección masiva post-importación desde asistente web"
_SOURCE_CODES = re.compile(r"Código\(s\) histórico\(s\) CODTRA:\s*([^.]*)\.", re.IGNORECASE)


def _identifier(value: object) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return str(int(value)) if value.is_integer() else str(value)
    return str(value).strip()


def _extract_codes(notes: str | None) -> set[str]:
    """Only match explicit original CODTRA provenance, never a remapped legajo."""
    match = _SOURCE_CODES.search(notes or "")
    if not match:
        return set()
    return {part.strip() for part in match.group(1).split(",") if part.strip()}


def parse_correction_file(content: bytes, filename: str) -> tuple[str, list[dict]]:
    """Require a single-column XLSX/CSV with employee_id or CODTRA as its header."""
    if not content:
        raise ValueError("El archivo está vacío.")
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("El archivo supera el máximo de 2 MB.")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    raw_rows: list[tuple] = []
    if ext == "xlsx":
        try:
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            try:
                sheet = workbook.active
                for index, values in enumerate(sheet.iter_rows(values_only=True), 1):
                    if index > MAX_IDENTIFIERS + 1:
                        raise ValueError("El archivo supera el límite de 15.000 identificadores.")
                    raw_rows.append(tuple(values))
            finally:
                workbook.close()
        except (BadZipFile, OSError, KeyError) as exc:
            raise ValueError("El Excel no es un archivo .xlsx válido.") from exc
    elif ext == "csv":
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Guardá el CSV con codificación UTF-8.") from exc
        header_line = next((line for line in decoded.splitlines() if line.strip()), "")
        delimiter = ";" if ";" in header_line else ("," if "," in header_line else ",")
        try:
            reader = csv.reader(io.StringIO(decoded, newline=""), delimiter=delimiter, strict=True)
            for index, values in enumerate(reader, 1):
                if index > MAX_IDENTIFIERS + 1:
                    raise ValueError("El archivo supera el límite de 15.000 identificadores.")
                raw_rows.append(tuple(values))
        except csv.Error as exc:
            raise ValueError("El CSV está mal formado.") from exc
    else:
        raise ValueError("Subí un archivo Excel .xlsx o CSV .csv.")

    if not raw_rows:
        raise ValueError("El archivo no contiene encabezados.")
    header = tuple(_identifier(value).strip() for value in raw_rows[0])
    populated_headers = [value for value in header if value]
    if len(populated_headers) != 1 or len(header) < 1 or not header[0]:
        raise ValueError("Debe existir exactamente una columna, con encabezado employee_id o CODTRA.")
    kind = header[0].casefold()
    if kind not in {"employee_id", "codtra"}:
        raise ValueError("El encabezado debe ser employee_id o CODTRA.")
    entries: list[dict] = []
    for row_number, values in enumerate(raw_rows[1:], 2):
        if any(_identifier(value) for value in values[1:]):
            raise ValueError(f"Fila {row_number}: se encontró una segunda columna. El archivo solo admite una.")
        identifier = _identifier(values[0]) if values else ""
        if not identifier:
            continue
        error = ""
        if len(identifier) > 80:
            error = "Identificador demasiado largo."
        elif kind == "employee_id" and (not identifier.isascii() or not identifier.isdecimal() or int(identifier) <= 0):
            error = "El employee_id debe ser un entero positivo."
        elif kind == "codtra" and ("." in identifier or not re.fullmatch(r"[A-Za-z0-9_-]+", identifier)):
            error = "CODTRA no tiene un formato válido."
        entries.append({"source_row": row_number, "identifier": identifier, "error": error})
    if not entries:
        raise ValueError("No se encontraron identificadores para procesar.")
    return kind, entries


def build_correction_preview(
    db: Session, *, kind: str, entries: list[dict], allowed_company_ids: set[int],
) -> dict:
    """Classify every identifier without writing to the database."""
    if not allowed_company_ids:
        raise ValueError("No hay empresas disponibles para este administrador.")
    if kind == "employee_id":
        identifiers = {int(item["identifier"]) for item in entries if not item["error"]}
        employees = list(db.scalars(select(Employee).where(
            Employee.company_id.in_(allowed_company_ids), Employee.id.in_(identifiers)
        )))
        matches = {str(employee.id): [employee] for employee in employees}
    else:
        employees = list(db.scalars(select(Employee).where(
            Employee.company_id.in_(allowed_company_ids),
            Employee.notes.contains("Código(s) histórico(s) CODTRA:"),
        )))
        matches: dict[str, list[Employee]] = {}
        for employee in employees:
            for source_code in _extract_codes(employee.notes):
                matches.setdefault(source_code, []).append(employee)

    matched = {employee.id: employee for group in matches.values() for employee in group}
    ids = list(matched)
    companies = {c.id: c for c in db.scalars(
        select(Company).where(Company.id.in_({e.company_id for e in matched.values()}))
    )} if matched else {}
    has_settlement = set(db.scalars(
        select(FinalSettlement.employee_id).where(FinalSettlement.employee_id.in_(ids))
    )) if ids else set()
    has_exit = set(db.scalars(
        select(EmployeeExit.employee_id).where(
            EmployeeExit.employee_id.in_(ids), EmployeeExit.status != "Cancelado"
        )
    )) if ids else set()

    reviewed: list[dict] = []
    seen: set[str] = set()
    for item in entries:
        identifier = item["identifier"]
        normalized = str(int(identifier)) if kind == "employee_id" and not item["error"] else identifier
        group = matches.get(normalized, []) if not item["error"] else []
        employee = group[0] if len(group) == 1 else None
        reason = item["error"]
        if not reason and normalized in seen:
            reason = "Identificador repetido en el archivo."
        elif not reason and not group:
            reason = "No se encontró en las empresas de este estudio."
        elif not reason and len(group) > 1:
            reason = "CODTRA ambiguo: corresponde a varios legajos o empresas."
        elif not reason and employee is not None:
            if employee.status != "Desvinculado":
                reason = "Ya está Activo." if employee.status == "Activo" else "Estado distinto de Desvinculado."
            elif employee.id in has_settlement:
                reason = "Tiene una liquidación final vinculada."
            elif employee.id in has_exit:
                reason = "Tiene un egreso formal no cancelado."
            elif companies.get(employee.company_id) is None or companies[employee.company_id].status == "Archivada":
                reason = "La empresa está archivada o no está disponible."
        seen.add(normalized)
        reviewed.append({
            "source_row": item["source_row"],
            "identifier": identifier,
            "employee_id": employee.id if employee else None,
            "name": employee.full_name if employee else "—",
            "code": employee.employee_code if employee else None,
            "company_id": employee.company_id if employee else None,
            "company_name": companies[employee.company_id].legal_name if employee and employee.company_id in companies else "—",
            "admission_date": employee.admission_date.isoformat() if employee and employee.admission_date else None,
            "termination_date": employee.termination_date.isoformat() if employee and employee.termination_date else None,
            "current_status": employee.status if employee else "No encontrado / ambiguo",
            "eligible": not bool(reason),
            "reason": reason,
        })
    ready = sum(row["eligible"] for row in reviewed)
    return {
        "kind": kind,
        "rows": reviewed,
        "summary": {"detected": len(entries), "ready": ready, "excluded": len(entries) - ready},
    }


def apply_correction(
    db: Session, *, preview: dict, allowed_company_ids: set[int],
    studio_id: int, user_email: str,
) -> int:
    """All-or-nothing update. Caller owns and commits the existing SQLAlchemy transaction."""
    rows = [row for row in preview["rows"] if row["eligible"]]
    if not rows:
        raise ValueError("No hay legajos válidos para reactivar.")
    ids = sorted({row["employee_id"] for row in rows})
    if len(ids) != len(rows):
        raise ValueError("La vista previa contiene legajos repetidos.")
    locked = list(db.scalars(
        select(Employee).where(Employee.id.in_(ids), Employee.company_id.in_(allowed_company_ids))
        .order_by(Employee.id).with_for_update()
    ))
    employees = {employee.id: employee for employee in locked}
    if len(employees) != len(ids):
        raise ValueError("La plantilla cambió desde la vista previa. Volvé a subir el archivo.")

    has_settlement = set(db.scalars(
        select(FinalSettlement.employee_id).where(FinalSettlement.employee_id.in_(ids))
    ))
    has_exit = set(db.scalars(
        select(EmployeeExit.employee_id).where(
            EmployeeExit.employee_id.in_(ids), EmployeeExit.status != "Cancelado"
        )
    ))
    company_ids = {employee.company_id for employee in locked}
    archived = set(db.scalars(select(Company.id).where(
        Company.id.in_(company_ids), Company.status == "Archivada"
    )))
    now = datetime.now(UTC)
    for row in rows:
        employee = employees[row["employee_id"]]
        if (
            employee.status != "Desvinculado"
            or employee.company_id != row["company_id"]
            or employee.employee_code != row["code"]
            or (employee.admission_date.isoformat() if employee.admission_date else None) != row["admission_date"]
            or (employee.termination_date.isoformat() if employee.termination_date else None) != row["termination_date"]
            or employee.id in has_settlement
            or employee.id in has_exit
            or employee.company_id in archived
        ):
            raise ValueError("Los datos cambiaron o existe una liquidación/egreso. Volvé a generar la vista previa.")
        if preview["kind"] == "codtra" and row["identifier"] not in _extract_codes(employee.notes):
            raise ValueError("El código histórico del legajo cambió. Volvé a revisar el archivo.")

    for row in rows:
        employee = employees[row["employee_id"]]
        old_termination = row["termination_date"] or "sin fecha"
        employee.status = "Activo"
        employee.termination_date = None
        employee.updated_at = now
        employee.updated_by = user_email
        detail = (
            f"{AUDIT_MESSAGE}; identificador {preview['kind']}={row['identifier']}; "
            f"estado anterior=Desvinculado; egreso anterior={old_termination}; "
            f"ingreso original preservado={row['admission_date']}."
        )
        db.add(EmployeeEvent(
            employee_id=employee.id,
            event_type="Corrección administrativa",
            title="Reactivación post-importación",
            detail=detail,
            effective_date=date.today(),
            created_by=user_email,
        ))
        db.add(AuditLog(
            studio_id=studio_id,
            user_email=user_email,
            action="reactivacion_post_importacion",
            entity="funcionario",
            entity_id=str(employee.id),
            detail=detail,
        ))
    db.flush()
    return len(rows)
