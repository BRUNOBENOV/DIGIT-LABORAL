"""Administrator-only web wizard for irreversible synthetic test-dossier purges."""
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
BASE = "/app/employees/{employee_id}/test-cleanup"


def _page(request, db, user, employee, preview, *, error="", status=200):
    response = core.render(
        request, "employee_test_cleanup.html", db, user, employee=employee,
        review=preview,
        review_token=signed_preview(user, employee, preview) if preview["can_purge"] else "",
        error=error,
    )
    response.status_code = status
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get(BASE)
def test_cleanup_preview(
    employee_id: int, request: Request,
    user: User = Depends(core.require_roles("administrador")),
    db: Session = Depends(core.get_db),
):
    employee = allowed_employee(db, user, employee_id)
    preview = purge_preview(db, employee)
    return _page(request, db, user, employee, preview)


@router.get(BASE + "/backup.json")
def test_cleanup_backup(
    employee_id: int,
    user: User = Depends(core.require_roles("administrador")),
    db: Session = Depends(core.get_db),
):
    employee = allowed_employee(db, user, employee_id)
    preview = purge_preview(db, employee)
    if not preview["can_purge"]:
        raise HTTPException(409, "El expediente contiene antecedentes protegidos. No se habilitó la exportación para depuración.")
    data = {
        **preview["backup"], "fingerprint_sha256": preview["fingerprint"],
        "exported_at_utc": datetime.now(UTC).isoformat(),
        "purpose": "Respaldo del expediente antes de depurar datos sintéticos.",
    }
    content = json.dumps(data, ensure_ascii=False, default=str, sort_keys=True, indent=2).encode("utf-8")
    core.write_audit(
        db, user, "exportar_respaldo_depuracion_pruebas", "funcionario", str(employee.id),
        json.dumps({"fingerprint": preview["fingerprint"], "company_id": employee.company_id,
                    "count": preview["total"]}, separators=(",", ":")),
    )
    db.commit()
    response = Response(content=content, media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="Digit-Laboral-Legajo-Prueba-{employee.id}-respaldo.json"',
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
    declare_synthetic: Annotated[str, Form()] = "",
    declare_no_external_use: Annotated[str, Form()] = "",
    backup_saved: Annotated[str, Form()] = "",
    user: User = Depends(core.require_roles("administrador")),
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
    if (declare_synthetic, declare_no_external_use, backup_saved) != ("on", "on", "on"):
        return _page(request, db, user, employee, preview,
                     error="Debés declarar que es un legajo sintético, sin efectos externos y con respaldo descargado.",
                     status=422)
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
        "snapshot_sha256": preview["fingerprint"],
        "deleted_counts": {group["key"]: group["count"] for group in preview["groups"]},
        "deleted_ids": {group["key"]: group["ids"] for group in preview["groups"]},
        "declarations": ["synthetic", "not_submitted_or_paid", "backup_exported"],
    }
    try:
        remove_test_dossier(db, employee, preview)
        core.write_audit(db, user, "depurar_legajo_sintetico", "funcionario", str(employee.id),
                         json.dumps(evidence, ensure_ascii=False, separators=(",", ":"), default=str))
        db.commit()
    except (PurgeConflict, IntegrityError):
        db.rollback()
        refreshed = allowed_employee(db, user, employee_id)
        return _page(request, db, user, refreshed, purge_preview(db, refreshed),
                     error="Una relación o un cambio impide la depuración. Se revirtió toda la operación.",
                     status=409)
    return RedirectResponse(
        f"/app/employees?company_id={evidence['company_id']}&test_cleaned=1",
        status_code=303,
    )
