"""Assisted export of approved REI movements and registration of the local lot."""
from __future__ import annotations

import hashlib
import json
import re
from calendar import monthrange
from dataclasses import asdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import main as core
from .compliance_service import OFFICIAL_PORTALS, _branch_context, _patronal_for_branch, register_batch
from .models import Company, ComplianceEvent, Employee, User
from .rei_movements import (
    MANUAL_REI_MOVEMENTS,
    MAX_MOVEMENTS,
    MAX_TEMPLATE_BYTES,
    MOVEMENT_BATCH_TYPE,
    MOVEMENT_FIELDS,
    MOVEMENT_TYPES,
    ReiCsvLayout,
    build_rei_movement_csv,
    read_rei_csv_layout,
)

router = APIRouter()
PATH = "/app/compliance/rei-movements"
Operator = Annotated[User, Depends(core.require_roles("administrador", "contador"))]
Database = Annotated[Session, Depends(core.get_db)]


def _review_token(user: User, step: str, values: dict) -> str:
    serializer = URLSafeTimedSerializer(core.settings.secret_key, salt=f"rei-movements-v1-{step}")
    return serializer.dumps({"user": user.id, "studio": user.studio_id, **values})


def _review_values(user: User, step: str, token: str) -> dict:
    serializer = URLSafeTimedSerializer(core.settings.secret_key, salt=f"rei-movements-v1-{step}")
    try:
        values = serializer.loads(token, max_age=1800)
    except BadData as exc:
        raise HTTPException(409, "La revisión venció o es inválida. Volvé a preparar el lote.") from exc
    if values["user"] != user.id or values["studio"] != user.studio_id:
        raise HTTPException(403, "La revisión corresponde a otro usuario o estudio.")
    return values


def _movements(company: Company, movement: str, period: str):
    if movement not in MOVEMENT_TYPES or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", period):
        raise HTTPException(400, "Seleccioná un tipo de movimiento y un mes válidos.")
    year, month = map(int, period.split("-"))
    try:
        start, end = date(year, month, 1), date(year, month, monthrange(year, month)[1])
    except ValueError as exc:
        raise HTTPException(400, "Seleccioná un mes válido.") from exc
    return select(ComplianceEvent).join(Employee, Employee.id == ComplianceEvent.employee_id).where(
        ComplianceEvent.company_id == company.id,
        ComplianceEvent.authority == "REI",
        ComplianceEvent.event_type == movement,
        ComplianceEvent.event_date.between(start, end),
        ComplianceEvent.status == "Validado",
        ComplianceEvent.batch_id.is_(None),
        Employee.company_id == company.id,
        Employee.ips_contributor.is_(True),
    ).options(selectinload(ComplianceEvent.employee), selectinload(ComplianceEvent.branch)).order_by(
        ComplianceEvent.event_date, ComplianceEvent.id
    )


def _patronals(db: Session, company: Company, events: list[ComplianceEvent]) -> dict[int, str]:
    _, profiles = _branch_context(db, company.id)
    return {
        event.id: (_patronal_for_branch(
            company, "REI", event.branch_id, profiles,
        ) or "").strip()
        for event in events
    }


def _selected_events(db: Session, company: Company, data: dict, *, lock: bool = False) -> list[ComplianceEvent]:
    ids = data["events"]
    if not 1 <= len(ids) <= MAX_MOVEMENTS or len(set(ids)) != len(ids) or any(not 0 < item <= 2_147_483_647 for item in ids):
        raise HTTPException(400, f"Seleccioná entre 1 y {MAX_MOVEMENTS} movimientos distintos.")
    query = _movements(company, data["movement"], data["period"]).where(ComplianceEvent.id.in_(ids))
    if lock:
        query = query.order_by(None).order_by(ComplianceEvent.id).with_for_update(of=ComplianceEvent)
    events = list(db.scalars(query))
    if len(events) != len(ids):
        raise HTTPException(409, "Algún movimiento seleccionado dejó de estar disponible para este lote.")
    return sorted(events, key=lambda event: (event.event_date, event.id))


def _csv_for_review(db: Session, company: Company, events: list[ComplianceEvent], data: dict) -> tuple[bytes, list[list[str]]]:
    patronal = data["patronal"]
    identities = {(event.employee_id, event.event_date) for event in events}
    candidates = select(ComplianceEvent).where(
        ComplianceEvent.company_id == company.id,
        ComplianceEvent.authority == "REI",
        ComplianceEvent.event_type == data["movement"],
        ComplianceEvent.employee_id.in_({item[0] for item in identities}),
        ComplianceEvent.event_date.in_({item[1] for item in identities}),
        ComplianceEvent.id.notin_(data["events"]),
        ComplianceEvent.status.in_(("Validado", "Exportado", "Presentado", "Aceptado")),
    )
    other_movements = [
        event for event in db.scalars(candidates)
        if (event.employee_id, event.event_date) in identities
    ]
    patronals = _patronals(db, company, events + other_movements)
    if not patronal or any(patronals[event.id] != patronal for event in events):
        raise ValueError("Elegí movimientos de un solo número patronal y confirmá ese mismo número del REI.")
    if len(identities) != len(events) or any(patronals[event.id] == patronal for event in other_movements):
        raise ValueError("Hay movimientos repetidos por funcionario, fecha y tipo. Revisá las comunicaciones antes de exportar.")
    return build_rei_movement_csv(
        company, events, ReiCsvLayout(**data["layout"]), data["fields"], data["constants"], patronal, data["date_format"],
    )


def _page(request: Request, db: Session, user: User, company: Company, **context):
    response = core.render(
        request, "rei_movements.html", db, user,
        company=company, path=PATH, movement_types=MOVEMENT_TYPES, movement_fields=MOVEMENT_FIELDS,
        max_movements=MAX_MOVEMENTS, manual=MANUAL_REI_MOVEMENTS, official_portal=OFFICIAL_PORTALS["REI"], **context,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get(PATH, response_class=HTMLResponse)
def rei_movements_page(request: Request, company_id: int, user: Operator, db: Database, movement: str = "Entrada", period: str = ""):
    company = core.company_allowed(db, user, company_id)
    period = period or core.current_paraguay_date().strftime("%Y-%m")
    events = list(db.scalars(_movements(company, movement, period).limit(MAX_MOVEMENTS + 1)))
    visible = events[:MAX_MOVEMENTS]
    return _page(
        request, db, user, company, stage="select", movement=movement, period=period, events=visible,
        more=len(events) > len(visible), patronals=_patronals(db, company, visible) if visible else {},
    )


@router.post(f"{PATH}/layout", response_class=HTMLResponse)
def rei_movement_layout(
    request: Request, user: Operator, db: Database,
    company_id: Annotated[int, Form()], movement: Annotated[str, Form()], period: Annotated[str, Form()],
    template: Annotated[UploadFile, File()],
    separator: Annotated[str, Form()], encoding: Annotated[str, Form()], first_row: Annotated[str, Form()],
    event_ids: Annotated[list[int] | None, Form()] = None,
):
    company = core.company_allowed(db, user, company_id)
    data = {"company_id": company.id, "movement": movement, "period": period, "events": event_ids or []}
    events = _selected_events(db, company, data)
    try:
        if not (template.filename or "").lower().endswith(".csv"):
            raise ValueError("Seleccioná un modelo con extensión CSV.")
        layout = read_rei_csv_layout(template.file.read(MAX_TEMPLATE_BYTES + 1), separator, encoding, first_row)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    data["layout"] = asdict(layout)
    patronals = set(_patronals(db, company, events).values())
    if len(patronals) != 1 or "" in patronals:
        raise HTTPException(409, "Seleccioná movimientos de una misma patronal IPS con número registrado.")
    return _page(
        request, db, user, company, stage="map", layout=layout, events=events, movement=movement, period=period,
        expected_patronal=next(iter(patronals)), review=_review_token(user, "layout", data),
    )


@router.post(f"{PATH}/preview", response_class=HTMLResponse)
def rei_movement_preview(
    request: Request, user: Operator, db: Database, review: Annotated[str, Form()],
    field: Annotated[list[str], Form()], constant: Annotated[list[str], Form()],
    patronal: Annotated[str, Form()], date_format: Annotated[str, Form()],
):
    data = _review_values(user, "layout", review)
    company = core.company_allowed(db, user, data["company_id"])
    events = _selected_events(db, company, data)
    data.update(fields=field, constants=[value.strip() for value in constant], patronal=patronal.strip(), date_format=date_format)
    layout = ReiCsvLayout(**data["layout"])
    try:
        content, rows = _csv_for_review(db, company, events, data)
    except ValueError as exc:
        return _page(
            request, db, user, company, stage="map", layout=layout, events=events,
            movement=data["movement"], period=data["period"], expected_patronal=", ".join(sorted(_patronals(db, company, events).values())),
            review=review, form=data, error=str(exc),
        )
    data["fingerprint"] = hashlib.sha256(content).hexdigest()
    return _page(
        request, db, user, company, stage="preview", layout=layout, rows=rows, events=events,
        movement=data["movement"], period=data["period"], patronal=data["patronal"],
        export_token=_review_token(user, "export", data),
    )


@router.post(f"{PATH}/export")
def rei_movement_export(
    user: Operator, db: Database, export_token: Annotated[str, Form()], confirmed: Annotated[str, Form()] = "",
):
    if confirmed != "si":
        raise HTTPException(400, "Confirmá la revisión del formato y los datos antes de generar el CSV.")
    data = _review_values(user, "export", export_token)
    company = core.company_allowed(db, user, data["company_id"])
    events = _selected_events(db, company, data, lock=True)
    try:
        content, _ = _csv_for_review(db, company, events, data)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if hashlib.sha256(content).hexdigest() != data["fingerprint"]:
        raise HTTPException(409, "Los datos cambiaron después de la revisión. Volvé a preparar el lote.")

    layout = ReiCsvLayout(**data["layout"])
    batch = register_batch(
        db, company=company, authority="REI", batch_type=MOVEMENT_BATCH_TYPE, period=data["period"],
        content=content, created_by=user.email, events=events,
    )
    batch.file_name = f"rei_movimientos_{batch.period}_lote-{batch.id}.csv"
    batch.storage_key = f"integrations/{company.id}/rei-movements/{batch.file_name}"
    batch.file_bytes = content if core.settings.storage_backend == "local" else None
    batch.payload_json = json.dumps({
        "movement": data["movement"], "patronal": data["patronal"], "csv_encoding": layout.encoding,
        "layout_sha256": hashlib.sha256(json.dumps(data["layout"], sort_keys=True).encode()).hexdigest(),
    }, ensure_ascii=False)
    core.storage.put(batch.storage_key, content, layout.media_type)
    core.write_audit(
        db, user, "exportar_movimientos_rei", "lote_integracion", str(batch.id),
        f"{data['movement']} · {batch.period} · {batch.item_count} comunicaciones · SHA-256 {batch.file_sha256}",
    )
    db.commit()
    return RedirectResponse(
        f"/app/compliance?company_id={company.id}&tab=batches&authority=REI&batch_id={batch.id}&created_batch=1",
        status_code=303,
    )
