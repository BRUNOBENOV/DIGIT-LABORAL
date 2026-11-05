"""Importador bidireccional: Excel REOP → cálculos salariales en revisión.

Previsualización de uso único y confirmación con verificación de permisos,
número patronal, identidad por C.I. y duplicados al confirmar.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import secrets
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import main as core
from .models import BranchComplianceProfile, CalculationRecord, Company, Employee
from .reop_salary_ingest import MAX_FILE_BYTES, parse_reop_workbook, _digits

router = APIRouter()
PREFIX = "/app/liquidaciones/salarios/importar-reop"
TYPES = ("salary", "suite_salary")


def _company(db: Session, user, company_id: int) -> Company:
    if company_id not in core.company_ids_for_user(db, user):
        raise HTTPException(404, "La empresa no está disponible para este usuario.")
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "La empresa no existe.")
    return company


def _cleanup_expired_reop_files() -> None:
    """Borra vistas y copias XLSX caducadas, también si nadie reabre el enlace."""
    cutoff = datetime.now(UTC).timestamp() - 4 * 3600
    for pattern in ("reop_salary_*.xlsx", "reop_salary_*.json.gz"):
        for path in core.IMPORT_DIR.glob(pattern):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except OSError:
                continue


def _preview_path(token: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", token or ""):
        raise HTTPException(422, "Token de vista previa inválido.")
    return core.IMPORT_DIR / f"reop_salary_{token}.json.gz"


def _source_path(token: str) -> Path:
    # El binario original solo existe mientras se revisa la importación.
    _preview_path(token)  # valida el token opaco
    return core.IMPORT_DIR / f"reop_salary_{token}.xlsx"


def _write_preview(token: str, payload: dict) -> None:
    path = _preview_path(token)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    path.chmod(0o600)


def _load_preview(token, user):
    path = _preview_path(token)
    if not path.exists():
        raise HTTPException(410, "Esta vista previa ya no está disponible. Subí la planilla nuevamente.")
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        created = datetime.fromisoformat(payload["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if created < datetime.now(UTC) - timedelta(hours=4):
            path.unlink(missing_ok=True)
            _source_path(token).unlink(missing_ok=True)
            raise HTTPException(410, "La vista previa venció. Subí el archivo nuevamente.")
        if payload["user_id"] != user.id or payload["studio_id"] != (user.studio_id or 0):
            raise HTTPException(403, "La vista previa corresponde a otro usuario o estudio.")
        return payload
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(422, "La vista previa de importación está dañada.") from exc


def _match_rows(db: Session, company: Company, payload: dict) -> tuple[list[dict], dict]:
    employees = list(db.scalars(select(Employee).where(Employee.company_id == company.id)))
    by_ci: dict[str, list[Employee]] = {}
    for employee in employees:
        ci = _digits(employee.document_number)
        if ci:
            by_ci.setdefault(ci, []).append(employee)
    periods = {row["period"] for row in payload["rows"] if row.get("period")}
    existing: set[tuple[int, str]] = set()
    if periods:
        existing = {
            (employee_id, period)
            for employee_id, period in db.execute(
                select(CalculationRecord.employee_id, CalculationRecord.reference_period).where(
                    CalculationRecord.company_id == company.id,
                    CalculationRecord.calculation_type.in_(TYPES),
                    CalculationRecord.reference_period.in_(periods),
                )
            )
        }
    allowed_patronals = {_digits(company.mtess_employer_number)}
    branches = db.scalars(
        select(BranchComplianceProfile).join(
            core.Branch, core.Branch.id == BranchComplianceProfile.branch_id
        ).where(core.Branch.company_id == company.id)
    )
    allowed_patronals.update(_digits(profile.mtess_employer_number) for profile in branches)
    allowed_patronals.discard("")
    all_rows = []
    flags = payload.get("flags") or {}
    stats = {"ready": 0, "blocked": 0, "existing": 0, "missing_employee": 0,
             "total": len(payload["rows"]), "periods": sorted(periods),
             "periods_suggested": sorted({row.get("period_hint") for row in payload["rows"] if row.get("period_hint")}),
             "patronales": sorted({row.get("patronal") for row in payload["rows"] if row.get("patronal")}),
             "date_suggestions": sum(bool(row.get("date_swap_proposal")) for row in payload["rows"]),
             "night_suggestions": sum(bool(row.get("night_total_proposal")) for row in payload["rows"]),
             "date_applied": bool(flags.get("correct_swapped_start")),
             "night_applied": bool(flags.get("night_column_is_total")),
             "date_example": next((r["date_swap_proposal"] for r in payload["rows"]
                                   if r.get("date_swap_proposal")), None),
             "night_example": next((r["night_total_proposal"] for r in payload["rows"]
                                    if r.get("night_total_proposal")), None)}
    for item in payload["rows"]:
        row = dict(item)
        problems = list(item.get("errors") or [])
        matched = by_ci.get(item["ci"]) or []
        if len(matched) != 1:
            code = "missing_employee"
            problems.append(
                "El C.I. corresponde a varios legajos. Revisá los duplicados."
                if len(matched) > 1 else
                "El C.I. no está registrado en los funcionarios de esta empresa."
            )
        elif not item.get("period"):
            code = "blocked"
        elif (matched[0].id, item["period"]) in existing:
            code = "existing"
            problems.append("Ya existe una liquidación para este funcionario y mes. No se sobrescribe.")
        else:
            code = "ready"
        if allowed_patronals and item["patronal"] not in allowed_patronals:
            problems.append("El N.º patronal de la planilla no coincide con el de esta empresa o sus sucursales.")
        elif not allowed_patronals:
            problems.append("La empresa no tiene N.º patronal REOP configurado. Completalo en Mantenimientos → Empresas antes de importar.")
        if problems and code == "ready":
            code = "blocked"
        elif problems and code not in {"existing", "missing_employee"}:
            code = "blocked"
        stats[code] += 1
        row["status"] = code
        row["problems"] = problems
        row["employee_id"] = matched[0].id if len(matched) == 1 else None
        row["employee_name"] = matched[0].full_name if len(matched) == 1 else "Sin coincidencia"
        all_rows.append(row)
    return all_rows, stats


@router.get(PREFIX, response_class=HTMLResponse)
def reop_salary_import_start(
    request: Request,
    company_id: int | None = None,
    user=Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    ids = core.company_ids_for_user(db, user)
    companies = list(db.scalars(select(Company).where(Company.id.in_(ids)).order_by(Company.legal_name))) if ids else []
    selected = db.get(Company, company_id) if company_id in ids else None
    return core.render(request, "reop_salary_ingest.html", db, user,
                       companies=companies, selected=selected, preview=None, rows=[],
                       summary={}, token="", imported=request.query_params.get("importados", ""),
                       error=request.query_params.get("error", ""))


@router.post(PREFIX + "/previsualizar")
async def reop_salary_import_preview(
    file: UploadFile = File(),
    company_id: int = Form(),
    user=Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    company = _company(db, user, company_id)
    content = await file.read(MAX_FILE_BYTES + 1)
    try:
        parsed = parse_reop_workbook(content, file.filename or "")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _cleanup_expired_reop_files()
    token = secrets.token_hex(16)
    payload = {
        **parsed, "company_id": company_id, "user_id": user.id,
        "studio_id": user.studio_id or 0,
        "created_at": datetime.now(UTC).isoformat(),
    }
    raw_path = _source_path(token)
    try:
        with raw_path.open("xb") as fh:
            fh.write(content)
        raw_path.chmod(0o600)
        _write_preview(token, payload)
    except OSError as exc:
        raw_path.unlink(missing_ok=True)
        raise HTTPException(500, "No se pudo crear la vista previa de salarios.") from exc
    core.write_audit(
        db, user, "previsualizar", "importacion_salarios_reop", token,
        f"SHA-256 {parsed['sha256']}; filas={parsed['source_rows']}; empresa={company_id}; sin aplicar correcciones",
    )
    db.commit()
    return RedirectResponse(PREFIX + "/" + token, status_code=303)


@router.get(PREFIX + "/{token}", response_class=HTMLResponse)
def reop_salary_import_preview_page(
    token: str,
    request: Request,
    user=Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    preview = _load_preview(token, user)
    company = _company(db, user, int(preview["company_id"]))
    rows, stats = _match_rows(db, company, preview)
    return core.render(request, "reop_salary_ingest.html", db, user,
                       companies=[], selected=company, preview=preview,
                       rows=rows[:100], summary=stats, token=token,
                       imported="", error="")


@router.post(PREFIX + "/{token}/resolver")
def reop_salary_import_resolve(
    token: str,
    action: str = Form(),
    user=Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    """Aplica una resolución explícita sobre la vista previa, nunca sobre el Excel."""
    payload = _load_preview(token, user)
    company = _company(db, user, int(payload["company_id"]))
    options = {
        "fecha_invertida": ("correct_swapped_start", "date_swap_proposal", True),
        "total_nocturno": ("night_column_is_total", "night_total_proposal", True),
        "deshacer_fecha": ("correct_swapped_start", "date_swap_proposal", False),
        "deshacer_nocturno": ("night_column_is_total", "night_total_proposal", False),
    }
    if action not in options:
        raise HTTPException(422, "Acción de revisión no reconocida.")
    key, candidate_key, enabled = options[action]
    if not any(row.get(candidate_key) for row in payload["rows"]):
        raise HTTPException(409, "El archivo no presenta esa incidencia.")
    if bool(payload["flags"].get(key)) == enabled:
        raise HTTPException(409, "La vista previa ya tiene aplicado ese tratamiento.")
    path = _source_path(token)
    try:
        original = path.read_bytes()
    except OSError as exc:
        raise HTTPException(410, "El Excel original de esta revisión ya no está disponible.") from exc
    if hashlib.sha256(original).hexdigest() != payload["sha256"]:
        raise HTTPException(409, "La copia temporal del Excel fue modificada; cargá el archivo nuevamente.")
    flags = dict(payload["flags"])
    flags[key] = enabled
    try:
        rechecked = parse_reop_workbook(
            original, payload["filename"],
            correct_swapped_start=bool(flags.get("correct_swapped_start")),
            night_column_is_total=bool(flags.get("night_column_is_total")),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if rechecked["sha256"] != payload["sha256"]:
        raise HTTPException(409, "El origen de la revisión no coincide.")
    payload.update({
        "rows": rechecked["rows"], "source_rows": rechecked["source_rows"],
        "flags": rechecked["flags"],
    })
    _write_preview(token, payload)
    core.write_audit(
        db, user, "resolver_incidencia", "importacion_salarios_reop", token,
        f"empresa={company.id}; accion={action}; archivo_sha256={payload['sha256']}",
    )
    db.commit()
    return RedirectResponse(PREFIX + "/" + token, status_code=303)


@router.post(PREFIX + "/{token}/confirmar")
def reop_salary_import_confirm(
    token: str,
    confirm: bool = Form(False),
    user=Depends(core.require_roles("administrador", "contador", "auxiliar")),
    db: Session = Depends(core.get_db),
):
    if not confirm:
        raise HTTPException(422, "Confirmá que revisaste la importación.")
    payload = _load_preview(token, user)
    company = _company(db, user, int(payload["company_id"]))
    rows, stats = _match_rows(db, company, payload)
    applicable = [row for row in rows if row["status"] == "ready"]
    if not applicable:
        raise HTTPException(409, "No hay filas aptas. Revisá las observaciones en la vista previa.")
    created = 0
    for row in applicable:
        # La previsualización es solo propuesta. Reconsultar al escribir evita
        # sobrescribir cambios ocurridos durante la revisión.
        prior = db.scalar(select(CalculationRecord.id).where(
            CalculationRecord.company_id == company.id,
            CalculationRecord.employee_id == row["employee_id"],
            CalculationRecord.reference_period == row["period"],
            CalculationRecord.calculation_type.in_(TYPES),
        ).limit(1))
        if prior:
            continue
        employee = db.get(Employee, row["employee_id"])
        if not employee or employee.company_id != company.id or _digits(employee.document_number) != row["ci"]:
            continue
        identity = {
            "employer": company.legal_name, "ruc": company.ruc or "",
            "employee": employee.full_name, "ci": employee.document_number,
            "position": employee.position or "", "payment_method": row["payment_method"],
        }
        inputs = {
            "kind": "salary", "month": row["period"], **identity,
            "period_start": row["period_start"], "period_end": row["period_end"],
            "days_worked": row["days_worked"], "hours_worked": row["hours_worked"],
            "extra_hours": row["extra_hours"], "pieces_or_tasks": row["pieces_or_tasks"],
            "reop_import_sha256": payload["sha256"], "reop_import_source_row": row["source_row"],
            "reop_employer_number": row["patronal"], "reop_payment_code": row["payment_code"],
            "reop_import_options": payload["flags"],
            "reop_original_night_total_control": row.get("night_total_control"),
            "apply_ips": True,
        }
        saved = {
            "kind": "salary", "title": "Salario importado de planilla REOP",
            "identity": identity, "period": row["period"],
            "earnings": row["earnings"], "deductions": row["deductions"],
            "gross": row["gross"], "discounts": row["discounts"], "net": row["net"],
            "issued_date": date.today().strftime("%d/%m/%Y"),
            "warnings": ["Origen: Excel REOP cargado manualmente. Pendiente de revisión y aprobación en DIGIT-LABORAL.",
                         *row.get("warnings", [])],
            "notes": "Datos copiados de planilla REOP sin recalcular valores.",
            "partial": False,
        }
        record = CalculationRecord(
            company_id=company.id, employee_id=employee.id,
            calculation_type="suite_salary", reference_period=row["period"],
            input_json=json.dumps(inputs, ensure_ascii=False),
            result_json=json.dumps(saved, ensure_ascii=False),
            amount=row["net"], status="Borrador",
            source="Importación Excel REOP", notes=f"Origen REOP; fila {row['source_row']}; SHA {payload['sha256'][:12]}",
            created_by=user.full_name,
        )
        db.add(record)
        created += 1
    if not created:
        raise HTTPException(409, "Los registros ya fueron importados por otra sesión. No se crearon duplicados.")
    core.write_audit(
        db, user, "importar", "importacion_salarios_reop", token,
        f"empresa={company.id}; archivo_sha256={payload['sha256']}; creados={created}; "
        f"omitidos={stats['total'] - created}; estado=Borrador",
    )
    db.commit()
    _preview_path(token).unlink(missing_ok=True)
    _source_path(token).unlink(missing_ok=True)
    return RedirectResponse(PREFIX + f"?company_id={company.id}&importados={created}", status_code=303)
