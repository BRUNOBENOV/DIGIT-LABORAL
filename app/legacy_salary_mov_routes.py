"""FastAPI UI for source-preserving MOV historic payroll imports.

Registered from app.main after authentication / tenant helpers are defined.
"""
from __future__ import annotations

import gzip
import io
import json
import re
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .models import Company, Employee, EmployeeEvent, User
from .legacy_salary_mov_import import (
    EVENT_TYPE, MAX_BYTES, event_data, make_mov_event,
    parse_legacy_mov_workbook, preview_mov_import,
)


def register_routes(
    app, *, import_dir: Path, render, get_db, require_user,
    require_roles, company_ids_for_user, write_audit,
):
    """Install the protected import and read-only history routes."""
    import_dir.mkdir(parents=True, exist_ok=True)

    def preview_path(token: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", token or ""):
            raise HTTPException(404, "Identificador de importación inválido.")
        return import_dir / f"legacy_mov_{token}.json.gz"

    def own_preview(user: User, token: str) -> dict:
        path = preview_path(token)
        if not path.is_file():
            raise HTTPException(404, "El análisis expiró. Volvé a subir el archivo.")
        try:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                payload = json.load(stream)
            created = datetime.fromisoformat(payload["created_at"])
        except (OSError, ValueError, KeyError) as exc:
            raise HTTPException(422, "La vista previa no se pudo recuperar.") from exc
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if created < datetime.now(UTC) - timedelta(hours=4):
            path.unlink(missing_ok=True)
            raise HTTPException(410, "La vista previa venció después de cuatro horas.")
        if payload.get("user_id") != user.id or payload.get("studio_id") != (user.studio_id or 0):
            raise HTTPException(403, "Esta importación pertenece a otro usuario o estudio.")
        return payload

    @app.get("/app/import/legacy-movements", response_class=HTMLResponse)
    def mov_import_start(
        request: Request,
        user: User = Depends(require_roles("administrador", "contador")),
        db: Session = Depends(get_db),
    ):
        return render(request, "legacy_mov_import.html", db, user, preview=None)

    @app.post("/app/import/legacy-movements/preview")
    async def mov_import_upload(
        file: UploadFile = File(),
        user: User = Depends(require_roles("administrador", "contador")),
        db: Session = Depends(get_db),
    ):
        content = await file.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise HTTPException(413, "La planilla supera los 10 MB permitidos.")
        try:
            parsed = parse_legacy_mov_workbook(content, file.filename or "")
            plan = preview_mov_import(db, parsed, set(company_ids_for_user(db, user)))
        except (ValueError, OSError, zipfile.BadZipFile) as exc:
            raise HTTPException(422, str(exc)) from exc
        token = uuid.uuid4().hex
        payload = {
            "user_id": user.id, "studio_id": user.studio_id or 0,
            "created_at": datetime.now(UTC).isoformat(),
            "parsed": parsed, "employee_mapping": plan["employee_mapping"],
        }
        with gzip.open(preview_path(token), "wt", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
        summary = plan["summary"]
        write_audit(
            db, user, "previsualizar", "importacion_historica_mov", token,
            f"MOV SHA256={parsed['sha256']} · {summary['source_rows']} filas, "
            f"{summary['ready']} elegibles, {summary['already_imported']} existentes, "
            f"{summary['rejected']} sin vínculo, {summary['conflicts']} conflictos.",
        )
        db.commit()
        return RedirectResponse(f"/app/import/legacy-movements/{token}", status_code=303)

    @app.get("/app/import/legacy-movements/{token}", response_class=HTMLResponse)
    def mov_import_review(
        token: str,
        request: Request,
        user: User = Depends(require_roles("administrador", "contador")),
        db: Session = Depends(get_db),
    ):
        payload = own_preview(user, token)
        plan = preview_mov_import(db, payload["parsed"], set(company_ids_for_user(db, user)))
        return render(
            request, "legacy_mov_import.html", db, user,
            preview=plan, token=token, source_filename=payload["parsed"]["filename"],
            source_sha256=payload["parsed"]["sha256"],
        )

    @app.post("/app/import/legacy-movements/{token}/confirm")
    def mov_import_confirm(
        token: str,
        verified: str = Form(""),
        user: User = Depends(require_roles("administrador", "contador")),
        db: Session = Depends(get_db),
    ):
        if verified != "si":
            raise HTTPException(400, "Confirmá la verificación de coincidencias.")
        payload = own_preview(user, token)
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"legacy-mov:{user.studio_id or 0}"},
            )
        plan = preview_mov_import(db, payload["parsed"], set(company_ids_for_user(db, user)))
        original_mapping = payload.get("employee_mapping") or {}
        current_mapping = plan["employee_mapping"]
        if any(current_mapping.get(key) != id_value for key, id_value in original_mapping.items()):
            raise HTTPException(
                409, "Las vinculaciones cambiaron desde la vista previa. "
                "Revisá la importación antes de confirmar.",
            )
        events = []
        count = 0
        for row in payload["parsed"]["rows"]:
            if plan["states"].get(row["legacy_key"]) != "listo":
                continue
            employee_id = current_mapping.get(row["legacy_key"])
            if not employee_id:
                continue
            events.append(make_mov_event(row, employee_id, payload["parsed"]["filename"], user.email))
            if len(events) >= 500:
                db.add_all(events)
                db.flush()
                count += len(events)
                events.clear()
        if events:
            db.add_all(events)
            db.flush()
            count += len(events)
            events.clear()
        summary = plan["summary"]
        write_audit(
            db, user, "importar", "importacion_historica_mov", token,
            f"MOV SHA256={payload['parsed']['sha256']} · {count} antecedentes incorporados; "
            f"{summary['already_imported']} omitidos por existir; {summary['rejected']} rechazados; "
            f"{summary['conflicts']} conflictos; {summary['warnings']} advertencias. "
            "Sin alterar nóminas, recibos, salarios actuales ni presentaciones oficiales.",
        )
        db.commit()
        preview_path(token).unlink(missing_ok=True)
        return RedirectResponse(
            "/app/legacy-movements?" + urlencode({
                "imported": count,
                "existing": summary["already_imported"],
                "rejected": summary["rejected"],
                "conflicts": summary["conflicts"],
            }), status_code=303,
        )

    @app.get("/app/legacy-movements", response_class=HTMLResponse)
    def mov_history(
        request: Request,
        page: int = 1,
        month: str = "",
        company_id: int | None = None,
        employee_id: int | None = None,
        user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ):
        allowed = set(company_ids_for_user(db, user))
        if company_id is not None and company_id not in allowed:
            raise HTTPException(404, "Empresa no autorizada.")
        if employee_id is not None:
            employee = db.get(Employee, employee_id)
            if not employee or employee.company_id not in allowed or (
                company_id is not None and employee.company_id != company_id
            ):
                raise HTTPException(404, "Funcionario no autorizado.")
        conditions = [
            Employee.company_id.in_(allowed) if allowed else Employee.company_id == -1,
            EmployeeEvent.event_type == EVENT_TYPE,
        ]
        if company_id is not None:
            conditions.append(Employee.company_id == company_id)
        if employee_id is not None:
            conditions.append(EmployeeEvent.employee_id == employee_id)
        month = month.strip()
        if month:
            if not re.fullmatch(r"(19|20)\d{2}-(0[1-9]|1[0-2])", month):
                raise HTTPException(422, "Mes inválido. Usá AAAA-MM.")
            from datetime import date
            conditions.append(EmployeeEvent.effective_date == date.fromisoformat(month + "-01"))
        query = select(EmployeeEvent).join(Employee).where(*conditions)
        total = int(db.scalar(select(func.count(EmployeeEvent.id)).join(Employee).where(*conditions)) or 0)
        pages = max(1, (total + 49) // 50)
        page = min(max(1, page), pages)
        items = list(db.scalars(query.order_by(
            EmployeeEvent.effective_date.desc(), EmployeeEvent.id.desc()
        ).limit(50).offset((page - 1) * 50)))
        rows = [{"event": event, "data": event_data(event.detail)} for event in items]
        filters = {}
        if company_id is not None:
            filters["company_id"] = company_id
        if employee_id is not None:
            filters["employee_id"] = employee_id
        if month:
            filters["month"] = month
        return render(
            request, "legacy_mov_history.html", db, user,
            rows=rows, total=total, page=page, pages=pages,
            month=month, company_id=company_id, employee_id=employee_id,
            previous_query=urlencode({**filters, "page": page - 1}),
            next_query=urlencode({**filters, "page": page + 1}),
        )
