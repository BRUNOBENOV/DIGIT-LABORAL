"""Role-controlled wizard for auditable dossier cleanup with evidence checks."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import main as core
from .employee_deletion_routes import allowed_employee
from .models import AuditLog, User
from .test_dossier_cleanup import (
    PurgeConflict, purge_preview, remove_test_dossier, signed_preview, verify_preview,
)

router = APIRouter()
BASE = "/app/employees/{employee_id}/cleanup"
LEGACY_BASE = "/app/employees/{employee_id}/test-cleanup"
CLEANUP_REASONS = (
    "Carga errónea", "Registro duplicado", "Importación incorrecta",
    "Rectificación de datos", "Otro motivo documentado",
)


def _page(request, db, user, employee, preview, *, error="", status=200):
    response = core.render(
        request, "employee_test_cleanup.html", db, user, employee=employee,
        review=preview,
        review_token=signed_preview(user, employee, preview) if preview["can_purge"] else "",
        error=error, cleanup_reasons=CLEANUP_REASONS,
    )
    response.status_code = status
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get(BASE)
def test_cleanup_preview(
    employee_id: int, request: Request,
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    employee = allowed_employee(db, user, employee_id)
    preview = purge_preview(db, employee)
    return _page(request, db, user, employee, preview)


@router.get(LEGACY_BASE)
def legacy_test_cleanup(employee_id: int,
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    allowed_employee(db, user, employee_id)
    return RedirectResponse(f"/app/employees/{employee_id}/cleanup", status_code=303)


@router.get(LEGACY_BASE + "/backup.json")
def legacy_test_cleanup_backup(employee_id: int,
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    allowed_employee(db, user, employee_id)
    return RedirectResponse(f"/app/employees/{employee_id}/cleanup/backup.json", status_code=303)


@router.get(BASE + "/backup.json")
def test_cleanup_backup(
    employee_id: int,
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    employee = allowed_employee(db, user, employee_id)
    preview = purge_preview(db, employee)
    if not preview["can_purge"]:
        raise HTTPException(409, "El expediente contiene antecedentes protegidos. No se habilitó la exportación para depuración.")
    data = {
        **preview["backup"], "fingerprint_sha256": preview["fingerprint"],
        "exported_at_utc": datetime.now(UTC).isoformat(),
        "purpose": "Respaldo del expediente para una depuración administrativa controlada.",
    }
    content = json.dumps(data, ensure_ascii=False, default=str, sort_keys=True, indent=2).encode("utf-8")
    core.write_audit(
        db, user, "exportar_respaldo_depuracion", "funcionario", str(employee.id),
        json.dumps({"fingerprint": preview["fingerprint"], "company_id": employee.company_id,
                    "count": preview["total"]}, separators=(",", ":")),
    )
    db.commit()
    response = Response(content=content, media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="Digit-Laboral-Legajo-{employee.id}-respaldo.json"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })
    return response


@router.post(BASE)
def test_cleanup_confirm(
    employee_id: int, request: Request,
    token: Annotated[str, Form()] = "",
    confirmation: Annotated[str, Form()] = "",
    reason: Annotated[str, Form()] = "",
    reason_type: Annotated[str, Form()] = "",
    declare_eligible: Annotated[str, Form()] = "",
    declare_no_external_use: Annotated[str, Form()] = "",
    backup_saved: Annotated[str, Form()] = "",
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    employee = allowed_employee(db, user, employee_id, lock=True)
    preview = purge_preview(db, employee)
    if not preview["can_purge"]:
        return _page(request, db, user, employee, preview,
                     error="Hay documentos, pagos, presentaciones o vínculos protegidos. No se eliminó ningún registro.",
                     status=409)
    if not verify_preview(token, user, employee, preview):
        return _page(request, db, user, employee, preview,
                     error="La revisión venció o los datos cambiaron. Volvé a revisar y descargar el respaldo.",
                     status=409)
    if confirmation.strip() != preview["confirmation"]:
        return _page(request, db, user, employee, preview,
                     error="Escribí exactamente la frase de confirmación.", status=422)
    if (declare_eligible, declare_no_external_use, backup_saved) != ("on", "on", "on"):
        return _page(request, db, user, employee, preview,
                     error="Confirmá que la depuración corresponde a una corrección legítima, que no hay documentos entregados ni obligaciones de conservación pendientes y que descargaste el respaldo.",
                     status=422)
    if reason_type not in CLEANUP_REASONS:
        return _page(request, db, user, employee, preview,
                     error="Seleccioná una causa de depuración válida.", status=422)
    if not (12 <= len(reason.strip()) <= 600):
        return _page(request, db, user, employee, preview,
                     error="Indicá el motivo específico entre 12 y 600 caracteres.", status=422)
    # The actual backup download is independently logged. Checkbox alone is
    # insufficient. Changes to the snapshot invalidate the recorded digest.
    previous_backups = db.scalars(select(AuditLog).where(
        AuditLog.studio_id == user.studio_id,
        AuditLog.user_email == user.email,
        AuditLog.action == "exportar_respaldo_depuracion_pruebas",
        AuditLog.entity == "funcionario",
        AuditLog.entity_id == str(employee.id),
    ).order_by(AuditLog.id.desc()).limit(30))
    saved = any(
        json.loads(log.detail).get("fingerprint") == preview["fingerprint"]
        for log in previous_backups
    )
    if not saved:
        return _page(request, db, user, employee, preview,
                     error="Primero descargá el respaldo JSON actualizado de este legajo.", status=409)

    evidence = {
        "company_id": employee.company_id,
        "employee_id": employee.id,
        "employee_code": employee.employee_code,
        "employee_name": employee.full_name,
        "previous_status": employee.status,
        "reason": reason.strip(),
        "reason_type": reason_type,
        "snapshot_sha256": preview["fingerprint"],
        "deleted_counts": {group["key"]: group["count"] for group in preview["groups"]},
        "deleted_ids": {group["key"]: group["ids"] for group in preview["groups"]},
        "declarations": ["documented_correction_no_retention", "not_submitted_delivered_or_paid", "backup_exported"],
    }
    try:
        remove_test_dossier(db, employee, preview)
        core.write_audit(db, user, "depurar_legajo_controlado", "funcionario", str(employee.id),
                         json.dumps(evidence, ensure_ascii=False, separators=(",", ":"), default=str))
        db.commit()
    except (PurgeConflict, IntegrityError):
        db.rollback()
        refreshed = allowed_employee(db, user, employee_id)
        return _page(request, db, user, refreshed, purge_preview(db, refreshed),
                     error="Una relación o un cambio impide la depuración. Se revirtió toda la operación.",
                     status=409)
    return RedirectResponse(
        f"/app/employees?company_id={evidence['company_id']}&cleaned=1",
        status_code=303,
    )
