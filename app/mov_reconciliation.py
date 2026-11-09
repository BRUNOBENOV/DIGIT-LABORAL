"""Professional review of imported MOV evidence without fabricating salary approvals.

A historical MOV row is never a new CalculationRecord, payment or REOP/REI receipt.
Reconciliation attaches metadata to the immutable EmployeeEvent source and may
reference a unique, already approved operational salary with an identical amount.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .legacy_salary_mov_import import EVENT_TYPE, event_data
from .models import (
    CalculationRecord, Employee, EmployeeEvent, HistoricalMovReconciliation, User,
)

VALIDATED = "Validado como antecedente"
MATCHED = "Conciliado"
PENDING = "Sin conciliar"
APPROVED = ("Aprobado", "Validado")
SALARY_TYPES = ("salary", "suite_salary")


def source_amount(data: dict) -> int | None:
    """Read exact integer source SALARI. Never infer a missing amount or net pay."""
    raw = str((data.get("values") or {}).get("SALARI") or "").strip()
    try:
        value = Decimal(raw)
        if not value.is_finite() or value <= 0 or value != value.to_integral_value():
            return None
        return int(value) if value <= 2_147_483_647 else None
    except (InvalidOperation, ValueError):
        return None


def valid_period(data: dict) -> bool:
    value = str(data.get("period") or "")
    if len(value) != 7 or value[4] != "-":
        return False
    try:
        year, month = int(value[:4]), int(value[5:])
        return 1900 <= year <= 2100 and 1 <= month <= 12
    except ValueError:
        return False


def _lock_studio(db: Session, studio_id: int) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"mov-reconciliation:{studio_id}"},
        )


def _get_event(db: Session, event_id: int, allowed_ids: set[int]):
    event = db.get(EmployeeEvent, event_id)
    if not event or event.event_type != EVENT_TYPE or event.employee.company_id not in allowed_ids:
        raise HTTPException(404, "Movimiento histórico MOV no encontrado en este estudio.")
    data = event_data(event.detail)
    if not data:
        raise HTTPException(422, "El antecedente no conserva datos MOV verificables.")
    return event, data


def _check_source(event: EmployeeEvent, data: dict) -> None:
    if not valid_period(data) or source_amount(data) is None:
        raise HTTPException(409, "El MOV no tiene período o importe SALARI íntegro y válido.")
    if event.effective_date.strftime("%Y-%m") != data["period"]:
        raise HTTPException(409, "El período de origen no coincide con el registro del movimiento.")
    if not data.get("source_hash") or len(str(data["source_hash"])) != 64:
        raise HTTPException(409, "El movimiento carece de huella de origen verificable.")
    company_code = str(data.get("company_code") or "").strip()
    legacy_code = str(event.employee.company.legacy_code or "").strip()
    if company_code and legacy_code and company_code != legacy_code:
        raise HTTPException(409, "El código de empresa del MOV difiere de la empresa vinculada.")


def _eligible_calculations(db: Session, event: EmployeeEvent, data: dict):
    return list(db.scalars(select(CalculationRecord).where(
        CalculationRecord.employee_id == event.employee_id,
        CalculationRecord.company_id == event.employee.company_id,
        CalculationRecord.reference_period == data["period"],
        CalculationRecord.calculation_type.in_(SALARY_TYPES),
        CalculationRecord.status.in_(APPROVED),
    ).order_by(CalculationRecord.id)))


def _save_review(db, user, event, data, *, record=None, notes=""):
    review = db.scalar(select(HistoricalMovReconciliation).where(
        HistoricalMovReconciliation.event_id == event.id
    ))
    if review and review.status != PENDING:
        raise HTTPException(409, "Este movimiento ya fue revisado. Reabrí la revisión si necesitás corregirlo.")
    if record is not None:
        used = db.scalar(select(HistoricalMovReconciliation).where(
            HistoricalMovReconciliation.calculation_record_id == record.id,
            HistoricalMovReconciliation.event_id != event.id,
        ))
        if used:
            raise HTTPException(409, "Esa liquidación ya fue conciliada con otro MOV.")
    if review is None:
        review = HistoricalMovReconciliation(
            studio_id=user.studio_id, company_id=event.employee.company_id,
            employee_id=event.employee_id, event_id=event.id,
        )
        db.add(review)
    review.status = MATCHED if record is not None else VALIDATED
    review.calculation_record_id = record.id if record is not None else None
    review.source_hash = data["source_hash"]
    review.notes = notes.strip()
    review.reviewed_by = user.email
    review.reviewed_at = datetime.now(UTC)
    return review


def _bulk_candidates(db: Session, allowed_ids: set[int]) -> tuple[list, int]:
    """Unambiguous exact matches only; never auto-approve otherwise."""
    if not allowed_ids:
        return [], 0
    events = list(db.scalars(select(EmployeeEvent).join(
        Employee, Employee.id == EmployeeEvent.employee_id
    ).where(
        Employee.company_id.in_(allowed_ids),
        EmployeeEvent.event_type == EVENT_TYPE,
    ).order_by(EmployeeEvent.id)))
    reviews = {v.event_id: v for v in db.scalars(select(HistoricalMovReconciliation).where(
        HistoricalMovReconciliation.company_id.in_(allowed_ids),
    ))}
    keys = Counter()
    sources = {}
    for event in events:
        data = event_data(event.detail) or {}
        sources[event.id] = data
        keys[(event.employee_id, data.get("period"))] += 1
    approved = list(db.scalars(select(CalculationRecord).where(
        CalculationRecord.company_id.in_(allowed_ids),
        CalculationRecord.calculation_type.in_(SALARY_TYPES),
        CalculationRecord.status.in_(APPROVED),
    )))
    by_key = defaultdict(list)
    for item in approved:
        by_key[(item.employee_id, item.reference_period)].append(item)
    used_ids = {r.calculation_record_id for r in reviews.values() if r.calculation_record_id}
    matches = []
    for event in events:
        data = sources[event.id]
        key = (event.employee_id, data.get("period"))
        prior = reviews.get(event.id)
        if prior and prior.status != PENDING:
            continue
        if keys[key] != 1 or data.get("warnings") or not valid_period(data):
            continue
        if source_amount(data) is None or not data.get("source_hash"):
            continue
        try:
            _check_source(event, data)
        except HTTPException:
            continue
        candidates = by_key.get(key) or []
        if len(candidates) != 1:
            continue
        calculation = candidates[0]
        if calculation.id in used_ids or calculation.amount != source_amount(data):
            continue
        matches.append((event, data, calculation))
    return matches, len(events)


def register_routes(app, *, render, get_db, require_roles, company_ids_for_user, write_audit):
    @app.get("/app/mov-conciliation", response_class=HTMLResponse)
    def mov_reconciliation_index(
        request: Request,
        user: User = Depends(require_roles("administrador", "contador")),
        db: Session = Depends(get_db),
    ):
        matches, total = _bulk_candidates(db, set(company_ids_for_user(db, user)))
        return render(
            request, "mov_reconciliation.html", db, user,
            bulk=True, bulk_count=len(matches), total_mov=total, matches=matches[:20],
        )

    @app.get("/app/mov-conciliation/{event_id}", response_class=HTMLResponse)
    def mov_reconciliation_detail(
        event_id: int,
        request: Request,
        user: User = Depends(require_roles("administrador", "contador")),
        db: Session = Depends(get_db),
    ):
        event, data = _get_event(db, event_id, set(company_ids_for_user(db, user)))
        review = db.scalar(select(HistoricalMovReconciliation).where(
            HistoricalMovReconciliation.event_id == event.id
        ))
        candidates = _eligible_calculations(db, event, data) if valid_period(data) else []
        return render(
            request, "mov_reconciliation.html", db, user, bulk=False, event=event,
            source=data, amount=source_amount(data), valid=valid_period(data),
            review=review, candidates=candidates,
        )

    @app.post("/app/mov-conciliation/{event_id}")
    def mov_reconciliation_save(
        event_id: int,
        action: str = Form(""),
        calculation_id: str = Form(""),
        note: str = Form(""),
        confirmed: str = Form(""),
        expected_hash: str = Form(""),
        user: User = Depends(require_roles("administrador", "contador")),
        db: Session = Depends(get_db),
    ):
        if confirmed != "si":
            raise HTTPException(422, "Confirmá la revisión profesional antes de guardar.")
        allowed_ids = set(company_ids_for_user(db, user))
        _lock_studio(db, int(user.studio_id or 0))
        event, data = _get_event(db, event_id, allowed_ids)
        if not expected_hash or expected_hash != data.get("source_hash"):
            raise HTTPException(409, "Cambió el registro de origen. Volvé a abrir y verificar los datos.")
        if action not in {"validate", "match", "reopen"}:
            raise HTTPException(422, "Acción de conciliación no reconocida.")
        if len(note.strip()) < 8 or len(note) > 1000:
            raise HTTPException(422, "Indicá un motivo u observación de 8 a 1000 caracteres.")
        review = db.scalar(select(HistoricalMovReconciliation).where(
            HistoricalMovReconciliation.event_id == event.id,
            HistoricalMovReconciliation.studio_id == user.studio_id,
        ))
        if action == "reopen":
            if not review or review.status == PENDING:
                raise HTTPException(409, "El MOV ya está pendiente de revisión.")
            old_status = review.status
            old_calculation_id = review.calculation_record_id
            review.status = PENDING
            review.calculation_record_id = None
            review.notes = note.strip()
            review.reviewed_by = user.email
            review.reviewed_at = datetime.now(UTC)
            write_audit(db, user, "reabrir", "conciliacion_mov", str(event.id),
                        f"{old_status} -> pendiente; liquidación #{old_calculation_id}; {note.strip()}")
        else:
            _check_source(event, data)
            if data.get("warnings") and len(note.strip()) < 20:
                raise HTTPException(422, "Los MOV con advertencias requieren una justificación de al menos 20 caracteres.")
            linked = None
            if action == "match":
                try:
                    selected_id = int(calculation_id)
                except (ValueError, TypeError):
                    raise HTTPException(422, "Elegí una liquidación aprobada existente.") from None
                options = _eligible_calculations(db, event, data)
                linked = next((record for record in options if record.id == selected_id), None)
                if linked is None:
                    raise HTTPException(409, "La liquidación seleccionada ya no está aprobada o no corresponde al funcionario y período.")
                if linked.amount != source_amount(data):
                    raise HTTPException(409, "Los importes no coinciden. Podés validar el antecedente con observación, pero no conciliarlo con esa liquidación.")
            _save_review(db, user, event, data, record=linked, notes=note)
            write_audit(db, user, "conciliar" if linked else "validar", "conciliacion_mov", str(event.id),
                        f"MOV {data['period']}; SALARI {source_amount(data)}; "
                        f"origen {data['source_hash']}; liquidación #{linked.id if linked else 'sin vínculo'}; {note.strip()}")
        db.commit()
        return RedirectResponse(
            f"/app/mov-conciliation/{event.id}?saved={quote(action)}", status_code=303,
        )

    @app.post("/app/mov-conciliation/bulk")
    def mov_reconciliation_bulk(
        confirmed: str = Form(""),
        user: User = Depends(require_roles("administrador", "contador")),
        db: Session = Depends(get_db),
    ):
        if confirmed != "si":
            raise HTTPException(422, "Confirmá la conciliación de coincidencias exactas.")
        allowed = set(company_ids_for_user(db, user))
        _lock_studio(db, int(user.studio_id or 0))
        matches, _ = _bulk_candidates(db, allowed)
        count = 0
        for event, data, calculation in matches[:300]:
            _save_review(
                db, user, event, data, record=calculation,
                notes="Conciliación masiva: un único MOV y una única liquidación aprobada del mismo "
                      "funcionario y período; importe SALARI idéntico y origen sin advertencias.",
            )
            count += 1
        write_audit(db, user, "conciliar_masivo", "conciliacion_mov", str(user.studio_id or ""),
                    f"{count} MOV vinculados a liquidaciones aprobadas existentes; "
                    "sin crear recibos ni alterar salarios. Máximo 300 por lote.")
        db.commit()
        return RedirectResponse(f"/app/mov-conciliation?processed={count}", status_code=303)
