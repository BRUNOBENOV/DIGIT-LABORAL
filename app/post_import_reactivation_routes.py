"""Admin-only, temporary UI for correcting historical employee statuses."""
from __future__ import annotations

import gzip
import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from . import main as core
from .models import User
from .post_import_reactivation import (
    MAX_FILE_BYTES, apply_correction, build_correction_preview, parse_correction_file,
)

router = APIRouter()
PATH = "/app/maintenance/post-import"
ENABLED = os.getenv("DIGIT_POST_IMPORT_REACTIVATION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
core.templates.env.globals["post_import_reactivation_enabled"] = ENABLED


def _guard() -> None:
    if not ENABLED:
        raise HTTPException(404, "Esta herramienta temporal ya no está habilitada.")


def _path(token: str):
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        raise HTTPException(404, "Vista previa inválida.")
    return core.IMPORT_DIR / f"post_import_reactivation_{token}.json.gz"


def _load(token: str, user: User) -> dict:
    path = _path(token)
    if not path.is_file():
        raise HTTPException(410, "La vista previa expiró o ya fue utilizada. Volvé a cargar el archivo.")
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            preview = json.load(stream)
        created_at = datetime.fromisoformat(preview["created_at"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(410, "La vista previa no está disponible. Volvé a cargar el archivo.") from exc
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    if datetime.now(UTC) - created_at > timedelta(hours=2):
        path.unlink(missing_ok=True)
        raise HTTPException(410, "La vista previa caducó después de 2 horas.")
    if preview.get("user_id") != user.id or preview.get("studio_id") != user.studio_id:
        raise HTTPException(403, "Esta vista previa pertenece a otro usuario o estudio.")
    return preview


@router.get(PATH)
def start(
    request: Request,
    user: User = Depends(core.require_roles("administrador")),
    db: Session = Depends(core.get_db),
):
    _guard()
    return core.render(request, "post_import_reactivation.html", db, user, step="upload")


@router.post(PATH + "/preview")
async def upload_preview(
    file: UploadFile = File(...),
    user: User = Depends(core.require_roles("administrador")),
    db: Session = Depends(core.get_db),
):
    _guard()
    raw = await file.read(MAX_FILE_BYTES + 1)
    try:
        kind, entries = parse_correction_file(raw, file.filename or "")
        reviewed = build_correction_preview(
            db, kind=kind, entries=entries,
            allowed_company_ids=set(core.company_ids_for_user(db, user)),
        )
    except ValueError as exc:
        return RedirectResponse(f"{PATH}?error={quote(str(exc))}", status_code=303)
    token = uuid.uuid4().hex
    preview = {
        "token": token,
        "user_id": user.id,
        "studio_id": user.studio_id,
        "created_at": datetime.now(UTC).isoformat(),
        "filename": (file.filename or "archivo")[:180],
        **reviewed,
    }
    with gzip.open(_path(token), "wt", encoding="utf-8") as stream:
        json.dump(preview, stream, ensure_ascii=False)
    core.write_audit(
        db, user, "previsualizar", "correccion_post_importacion", token,
        f"{preview['filename']}; detectados={reviewed['summary']['detected']}; "
        f"aptos={reviewed['summary']['ready']}; excluidos={reviewed['summary']['excluded']}.",
    )
    db.commit()
    return RedirectResponse(f"{PATH}/{token}", status_code=303)


@router.get(PATH + "/{token}")
def show_preview(
    token: str,
    request: Request,
    user: User = Depends(core.require_roles("administrador")),
    db: Session = Depends(core.get_db),
):
    _guard()
    preview = _load(token, user)
    return core.render(
        request, "post_import_reactivation.html", db, user,
        step="preview", preview=preview, token=token,
    )


@router.post(PATH + "/{token}/confirm")
def confirm(
    token: str,
    confirmation: bool = Form(False),
    user: User = Depends(core.require_roles("administrador")),
    db: Session = Depends(core.get_db),
):
    _guard()
    if not confirmation:
        raise HTTPException(422, "Debés confirmar expresamente que los trabajadores siguen en la plantilla.")
    preview = _load(token, user)
    try:
        count = apply_correction(
            db, preview=preview,
            allowed_company_ids=set(core.company_ids_for_user(db, user)),
            studio_id=user.studio_id, user_email=user.email,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    _path(token).unlink(missing_ok=True)
    return RedirectResponse(
        f"/app/employees?status_filter=Activo&reactivated={count}", status_code=303
    )
