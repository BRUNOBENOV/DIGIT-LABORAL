"""Protected import wizard inside the existing Cálculo → Liquidación final workflow."""
from __future__ import annotations

import gzip
import json
import re
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import User
from .legacy_liq_import import (
    MAX_BYTES, make_liq_event, parse_legacy_liq_workbook, preview_liq_import,
)


def register_liq_routes(
    app, *, import_dir: Path, render, get_db, require_roles,
    company_ids_for_user, write_audit,
):
    import_dir.mkdir(parents=True, exist_ok=True)

    def _path(token: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", token or ""):
            raise HTTPException(404, "Identificador de análisis inválido.")
        return import_dir / f"legacy_liq_{token}.json.gz"

    def _own_preview(user: User, token: str) -> dict:
        path = _path(token)
        if not path.exists():
            raise HTTPException(404, "El análisis no está disponible. Volvé a subir el Excel.")
        try:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                payload = json.load(stream)
            created = datetime.fromisoformat(payload["created_at"])
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(422, "No se pudo leer la conciliación anterior.") from exc
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if created < datetime.now(UTC) - timedelta(hours=4):
            path.unlink(missing_ok=True)
            raise HTTPException(410, "El análisis caducó. Volvé a subir el Excel.")
        if payload.get("user_id") != user.id or payload.get("studio_id") != (user.studio_id or 0):
            raise HTTPException(403, "La importación pertenece a otra cuenta o estudio.")
        return payload

    @app.get("/app/import/legacy-liquidations", response_class=HTMLResponse)
    def legacy_liq_start(
        request: Request,
        user: User = Depends(require_roles("administrador", "contador")),
        db: Session = Depends(get_db),
    ):
        return render(request, "legacy_liq_import.html", db, user, preview=None)

    @app.post("/app/import/legacy-liquidations/preview")
    async def legacy_liq_upload(
        file: UploadFile = File(),
        user: User = Depends(require_roles("administrador", "contador")),
        db: Session = Depends(get_db),
    ):
        content = await file.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise HTTPException(413, "El archivo supera el límite de 10 MB.")
        try:
            parsed = parse_legacy_liq_workbook(content, file.filename or "")
            plan = preview_liq_import(db, parsed, set(company_ids_for_user(db, user)))
        except (ValueError, OSError, zipfile.BadZipFile) as exc:
            raise HTTPException(422, str(exc)) from exc
        token = uuid.uuid4().hex
        payload = {
            "user_id": user.id, "studio_id": user.studio_id or 0,
            "created_at": datetime.now(UTC).isoformat(),
            "parsed": parsed, "employee_mapping": plan["employee_mapping"],
        }
        with gzip.open(_path(token), "wt", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
        summary = plan["summary"]
        write_audit(
            db, user, "previsualizar", "importacion_historica_liq", token,
            f"LSLIQ SHA256={parsed['sha256']} · {summary['source_rows']} registros · "
            f"{summary['ready']} listos · {summary['rejected']} rechazados · "
            f"{summary['conflicts']} conflictos.",
        )
        db.commit()
        return RedirectResponse(f"/app/import/legacy-liquidations/{token}", status_code=303)

    @app.get("/app/import/legacy-liquidations/{token}", response_class=HTMLResponse)
    def legacy_liq_review(
        token: str,
        request: Request,
        user: User = Depends(require_roles("administrador", "contador")),
        db: Session = Depends(get_db),
    ):
        payload = _own_preview(user, token)
        plan = preview_liq_import(db, payload["parsed"], set(company_ids_for_user(db, user)))
        return render(
            request, "legacy_liq_import.html", db, user,
            preview=plan, token=token,
            source_filename=payload["parsed"]["filename"],
            source_sha256=payload["parsed"]["sha256"],
        )

    @app.post("/app/import/legacy-liquidations/{token}/confirm")
    def legacy_liq_confirm(
        token: str,
        verified: str = Form(""),
        user: User = Depends(require_roles("administrador", "contador")),
        db: Session = Depends(get_db),
    ):
        if verified != "si":
            raise HTTPException(422, "Confirmá la revisión de los legajos vinculados.")
        payload = _own_preview(user, token)
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"legacy-liq:{user.studio_id or 0}"},
            )
        plan = preview_liq_import(db, payload["parsed"], set(company_ids_for_user(db, user)))
        original_mapping = payload.get("employee_mapping") or {}
        actual_mapping = plan["employee_mapping"]
        if any(actual_mapping.get(key) != employee_id
               for key, employee_id in original_mapping.items()):
            raise HTTPException(409, "Cambió la vinculación de uno o más legajos. Revisá nuevamente la importación.")
        count = 0
        batch = []
        for row in payload["parsed"]["rows"]:
            if plan["states"].get(row["legacy_key"]) != "listo":
                continue
            employee_id = actual_mapping.get(row["legacy_key"])
            if employee_id is None:
                continue
            batch.append(make_liq_event(row, employee_id, payload["parsed"]["filename"], user.email))
            if len(batch) >= 350:
                db.add_all(batch)
                db.flush()
                count += len(batch)
                batch.clear()
        if batch:
            db.add_all(batch)
            db.flush()
            count += len(batch)
        summary = plan["summary"]
        write_audit(
            db, user, "importar", "importacion_historica_liq", token,
            f"LSLIQ SHA256={payload['parsed']['sha256']} · {count} antecedentes vinculados; "
            f"{summary['already_imported']} ya existentes, {summary['rejected']} no vinculados, "
            f"{summary['conflicts']} conflictos, {summary['warnings']} con advertencias. "
            "Sin crear ni modificar egresos, liquidaciones operativas, recibos o pagos.",
        )
        db.commit()
        _path(token).unlink(missing_ok=True)
        return RedirectResponse(
            "/app/liquidaciones?" + urlencode({
                "tipo": "settlement", "liq_imported": count,
                "liq_existing": summary["already_imported"],
                "liq_rejected": summary["rejected"],
                "liq_conflicts": summary["conflicts"],
            }) + "#labor-history", status_code=303,
        )
