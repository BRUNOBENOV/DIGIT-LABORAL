"""Labor exit workflow, final-settlement payment and non-destructive dossier archive.

Employment termination is distinct from accounting approval and proof of payment.
Historical imports do not create these manual exit workflows.
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import main as core
from .document_export import build_document_body, encode_metadata
from .models import (
    AuditLog, CalculationRecord, Company, Document, Employee, EmployeeEvent,
    EmployeeExit, FinalSettlement, GeneratedCertificate, Studio, User,
)
from .period_coverage import current_paraguay_date
from .salary_history import salary_at
from .database import SessionLocal, apply_session_tenant_context

router = APIRouter()

EXIT_REASONS = {
    "resignation": "Renuncia",
    "dismissal": "Despido sin causa",
    "justified": "Despido con causa",
    "worker_justified": "Retiro justificado",
    "fixed_term_expiration": "Vencimiento de contrato",
    "mutual_consent": "Mutuo consentimiento",
    "death": "Fallecimiento",
    "other": "Otro",
}
REVIEW_STATES = ("Pendiente de Cálculo", "En Revisión", "Aprobada", "Pagada")
ARCHIVE_MARKER = "ARCHIVE_STATE_V1:"

def latest_exit(db: Session, employee_id: int) -> EmployeeExit | None:
    return db.scalar(
        select(EmployeeExit).where(
            EmployeeExit.employee_id == employee_id,
            EmployeeExit.status != "Cancelado",
        ).order_by(EmployeeExit.id.desc()).limit(1)
    )

def latest_settlement(db: Session, employee_id: int) -> FinalSettlement | None:
    return db.scalar(
        select(FinalSettlement).where(FinalSettlement.employee_id == employee_id)
        .order_by(FinalSettlement.id.desc()).limit(1)
    )

def _allowed_employee(db: Session, user: User, employee_id: int) -> Employee:
    employee = db.get(Employee, employee_id)
    if not employee or employee.company_id not in core.company_ids_for_user(db, user):
        raise HTTPException(404, "Funcionario no encontrado en tu estudio.")
    return employee

def _allowed_exit(db: Session, user: User, exit_id: int) -> tuple[EmployeeExit, Employee]:
    exit_record = db.get(EmployeeExit, exit_id)
    if not exit_record or exit_record.company_id not in core.company_ids_for_user(db, user):
        raise HTTPException(404, "Egreso no encontrado.")
    employee = _allowed_employee(db, user, exit_record.employee_id)
    if employee.company_id != exit_record.company_id:
        raise HTTPException(409, "El egreso no corresponde a la empresa del legajo.")
    return exit_record, employee

def _allowed_settlement(db: Session, user: User, settlement_id: int) -> tuple[FinalSettlement, EmployeeExit, Employee]:
    settlement = db.get(FinalSettlement, settlement_id)
    if not settlement or settlement.company_id not in core.company_ids_for_user(db, user):
        raise HTTPException(404, "Liquidación final no encontrada.")
    exit_record, employee = _allowed_exit(db, user, settlement.employee_exit_id)
    if (settlement.employee_id != employee.id or settlement.company_id != exit_record.company_id):
        raise HTTPException(409, "La liquidación no corresponde al procedimiento.")
    return settlement, exit_record, employee

def _validated_upload(file: UploadFile, content: bytes) -> str:
    if not content:
        raise HTTPException(422, "El documento adjunto está vacío.")
    if len(content) > min(core.MAX_UPLOAD_SIZE, 5 * 1024 * 1024):
        raise HTTPException(413, "El documento excede el límite de 5 MB.")
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise HTTPException(422, "Solo se admiten documentos PDF, PNG o JPEG verificables.")

async def _attach_document(
    db: Session, employee: Employee, user: User, file: UploadFile,
    category: str, title: str,
) -> Document:
    raw = await file.read(min(core.MAX_UPLOAD_SIZE, 5 * 1024 * 1024) + 1)
    media_type = _validated_upload(file, raw)
    filename = core.safe_filename(file.filename or "respaldo")
    stored = f"documents/{employee.company_id}/{uuid.uuid4().hex}_{filename}"
    # Store the bytes in the database even with local storage so redeploys do not
    # destroy mandatory legal and accounting evidence.
    doc = Document(
        company_id=employee.company_id, employee_id=employee.id, category=category,
        title=title[:200], stored_name=stored, original_name=filename,
        content_type=media_type, content_bytes=raw, uploaded_by=user.email,
    )
    db.add(doc)
    return doc

def _issue_work_certificate(db: Session, employee: Employee, exit_record: EmployeeExit) -> GeneratedCertificate:
    """Generate an unsigned, downloadable draft with dated employment details."""
    today = current_paraguay_date()
    company = db.get(Company, employee.company_id)
    recorded_salary = salary_at(db, employee, exit_record.effective_date)
    meta = {
        "notes": "Borrador generado al registrar egreso; requiere revisión y firma del empleador.",
        "effective_date": exit_record.effective_date.isoformat(),
        "last_period_salary_amount": recorded_salary,
        "include_salary": "on",
    }
    title, body = build_document_body(
        "certificado_trabajo_a",
        company_name=company.legal_name, company_ruc=company.ruc,
        company_address=company.address, company_phone=company.phone,
        company_email=company.email, legal_representative=company.legal_representative,
        employee_name=employee.full_name, employee_document=employee.document_number,
        position=employee.position, admission_date=employee.admission_date,
        salary=recorded_salary, issue_date=today, city=company.city or "Ciudad del Este",
        metadata=meta,
    )
    item = GeneratedCertificate(
        company_id=employee.company_id, employee_id=employee.id,
        document_type="certificado_trabajo_a", title=title,
        city=(company.city or "Ciudad del Este")[:120], issue_date=today,
        company_name_snapshot=company.legal_name,
        employee_name_snapshot=employee.full_name,
        employee_document_snapshot=employee.document_number,
        position_snapshot=employee.position,
        admission_date_snapshot=employee.admission_date,
        salary_snapshot=recorded_salary, observations=encode_metadata(**meta),
        body=body, status="Borrador", created_by="Sistema · egreso",
    )
    db.add(item)
    db.flush()
    exit_record.constancia_certificate_id = item.id
    return item

def _make_exit_effective(db: Session, exit_record: EmployeeExit, employee: Employee, actor: User | None = None) -> bool:
    if exit_record.status != "Programado" or exit_record.effective_date > current_paraguay_date():
        return False
    exit_record.status = "Efectivo"
    exit_record.effective_at = datetime.now(UTC)
    if employee.status != "Archivado":
        employee.status = "Desvinculado"
    employee.termination_date = exit_record.effective_date
    employee.updated_at = datetime.now(UTC)
    employee.updated_by = actor.email if actor else "Sistema · egreso programado"
    db.add(EmployeeEvent(
        employee_id=employee.id, event_type="Egreso",
        title=f"Egreso efectivo · {EXIT_REASONS.get(exit_record.reason, exit_record.reason)}",
        detail=f"Procedimiento #{exit_record.id}; causal: {EXIT_REASONS.get(exit_record.reason, exit_record.reason)}; iniciado por: {exit_record.initiated_by}. Pago de liquidación registrado por separado.",
        effective_date=exit_record.effective_date,
        created_by=actor.email if actor else "Sistema",
    ))
    core.ensure_compliance_event(
        db, company_id=employee.company_id, employee_id=employee.id, branch_id=employee.branch_id,
        authority="REOP", event_type="Salida", event_date=exit_record.effective_date,
        due_date=None, payload={"employee_exit_id": exit_record.id, "source": "procedimiento_de_egreso"},
        created_by=actor.email if actor else "Sistema",
        source_key=f"employee:{employee.id}:exit-workflow:{exit_record.id}:reop",
    )
    if employee.ips_contributor:
        core.ensure_compliance_event(
            db, company_id=employee.company_id, employee_id=employee.id, branch_id=employee.branch_id,
            authority="REI", event_type="Salida", event_date=exit_record.effective_date,
            due_date=None, payload={"employee_exit_id": exit_record.id, "source": "procedimiento_de_egreso"},
            created_by=actor.email if actor else "Sistema",
            source_key=f"employee:{employee.id}:exit-workflow:{exit_record.id}:rei",
        )
    if not exit_record.constancia_certificate_id:
        _issue_work_certificate(db, employee, exit_record)
    return True

def sync_due_employee_exits(db: Session, *, employee_id: int | None = None) -> int:
    """Idempotently activate due notices; caller owns the transaction."""
    today = current_paraguay_date()
    query = select(EmployeeExit).where(
        EmployeeExit.status == "Programado",
        EmployeeExit.effective_date <= today,
    ).order_by(EmployeeExit.effective_date, EmployeeExit.id)
    if employee_id is not None:
        query = query.where(EmployeeExit.employee_id == employee_id)
    changed = 0
    for record in db.scalars(query):
        employee = db.get(Employee, record.employee_id)
        if employee and employee.company_id == record.company_id:
            changed += int(_make_exit_effective(db, record, employee))
    return changed

def sync_due_employee_exits_all_studios() -> int:
    """Periodic sweep, scoped tenant by tenant; no cross-tenant visibility."""
    count = 0
    with SessionLocal() as db:
        # RLS does not expose the studio registry to an unbound session.
        # Enumerate as the trusted service context, then scope every exit query.
        core.use_privileged_auth_context(db)
        studio_ids = list(db.scalars(select(Studio.id)))
        for studio_id in studio_ids:
            db.info["studio_id"] = studio_id
            db.info["is_superadmin"] = False
            apply_session_tenant_context(db)
            count += sync_due_employee_exits(db)
            db.commit()
    return count

@router.post("/app/employees/{employee_id}/exit")
async def register_exit(
    employee_id: int,
    effective_date: date = Form(...),
    reason: str = Form(...),
    initiated_by: str = Form(...),
    pre_notice_notified: str = Form(""),
    notice_date: str = Form(""),
    notes: str = Form(""),
    supporting_file: UploadFile | None = File(None),
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    employee = _allowed_employee(db, user, employee_id)
    today = current_paraguay_date()
    if employee.status != "Activo":
        raise HTTPException(409, "Solo se puede iniciar un egreso desde un legajo activo.")
    if latest_exit(db, employee.id):
        raise HTTPException(409, "Ya existe un procedimiento de egreso para este legajo.")
    if reason not in EXIT_REASONS or initiated_by not in {"Empleador", "Trabajador"}:
        raise HTTPException(422, "La causal o el iniciador del egreso no son válidos.")
    if effective_date < employee.admission_date:
        raise HTTPException(422, "La fecha de egreso no puede anteceder al ingreso.")
    notice_on = core.optional_date(notice_date, field="fecha de notificación") if notice_date else None
    future = effective_date > today
    if future and (pre_notice_notified != "on" or notice_on is None or notice_on > today or notice_on > effective_date):
        raise HTTPException(422, "El egreso futuro exige un preaviso/notificación ya comunicado y su fecha válida.")
    if len(notes) > 3000:
        raise HTTPException(422, "Las observaciones exceden los 3.000 caracteres.")
    exit_record = EmployeeExit(
        company_id=employee.company_id, employee_id=employee.id,
        effective_date=effective_date, reason=reason,
        initiated_by=initiated_by, pre_notice_notified=pre_notice_notified == "on",
        notice_date=notice_on, status="Programado", source="Manual",
        notes=notes.strip(), created_by=user.email,
    )
    db.add(exit_record)
    db.flush()
    db.add(FinalSettlement(
        company_id=employee.company_id, employee_id=employee.id,
        employee_exit_id=exit_record.id, status="Pendiente de Cálculo",
        created_by=user.email,
    ))
    employee.termination_date = effective_date
    employee.updated_by = user.email
    if supporting_file and supporting_file.filename:
        await _attach_document(
            db, employee, user, supporting_file, "Respaldo de egreso",
            f"Respaldo de egreso #{exit_record.id} · {EXIT_REASONS[reason]}",
        )
    core.add_employee_event(
        db, employee, user, "Egreso",
        f"{'Egreso programado' if future else 'Egreso registrado'} · {EXIT_REASONS[reason]}",
        f"Procedimiento #{exit_record.id}; inicia: {initiated_by}; fecha efectiva: {effective_date.isoformat()}; notificación: {notice_on or 'No informada'}; liquidación económica independiente.",
        today,
    )
    if not future:
        _make_exit_effective(db, exit_record, employee, user)
    core.write_audit(db, user, "registrar_egreso", "funcionario", str(employee.id), f"Procedimiento #{exit_record.id}, fecha {effective_date}, motivo {reason}")
    db.commit()
    return RedirectResponse(
        f"/app/liquidaciones?tipo=settlement&company_id={employee.company_id}&employee_id={employee.id}&exit_id={exit_record.id}",
        status_code=303,
    )

@router.post("/app/employees/{employee_id}/archive")
def archive_employee(
    employee_id: int, user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    employee = _allowed_employee(db, user, employee_id)
    if employee.status == "Archivado":
        return RedirectResponse(f"/app/employees/{employee.id}", status_code=303)
    state = {"status": employee.status, "termination_date": employee.termination_date.isoformat() if employee.termination_date else None}
    employee.status = "Archivado"
    employee.updated_by = user.email
    employee.updated_at = datetime.now(UTC)
    core.add_employee_event(db, employee, user, "Archivo", "Legajo archivado",
                            ARCHIVE_MARKER + json.dumps(state, ensure_ascii=False, separators=(",", ":")))
    core.write_audit(db, user, "archivar", "funcionario", str(employee.id), "Archivo lógico; se preservan relaciones.")
    db.commit()
    return RedirectResponse("/app/employees?show_archived=true&archived=1", status_code=303)

@router.post("/app/employees/{employee_id}/restore")
def restore_employee(
    employee_id: int, user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    employee = _allowed_employee(db, user, employee_id)
    if employee.status != "Archivado":
        raise HTTPException(409, "El legajo no está archivado.")
    archived = db.scalar(
        select(EmployeeEvent).where(
            EmployeeEvent.employee_id == employee.id,
            EmployeeEvent.event_type == "Archivo",
        ).order_by(EmployeeEvent.id.desc()).limit(1)
    )
    previous = {}
    if archived and archived.detail and archived.detail.startswith(ARCHIVE_MARKER):
        try:
            previous = json.loads(archived.detail[len(ARCHIVE_MARKER):])
        except (ValueError, TypeError):
            previous = {}
    previous_status = previous.get("status", "")
    if previous_status not in {"Activo", "Inactivo", "Desvinculado"}:
        previous_status = "Desvinculado" if employee.termination_date and employee.termination_date <= current_paraguay_date() else "Activo"
    exit_record = latest_exit(db, employee.id)
    if exit_record and exit_record.effective_date <= current_paraguay_date():
        _make_exit_effective(db, exit_record, employee, user)
        previous_status = "Desvinculado"
    employee.status = previous_status
    if exit_record:
        employee.termination_date = exit_record.effective_date
    elif previous.get("termination_date"):
        employee.termination_date = date.fromisoformat(previous["termination_date"])
    employee.updated_by = user.email
    employee.updated_at = datetime.now(UTC)
    core.add_employee_event(db, employee, user, "Archivo", "Legajo restaurado",
                            f"Estado anterior recuperado: {employee.status}. Sin borrado de documentos o liquidaciones.")
    core.write_audit(db, user, "restaurar", "funcionario", str(employee.id), employee.status)
    db.commit()
    return RedirectResponse(f"/app/employees/{employee.id}", status_code=303)

@router.get("/app/final-settlements/{settlement_id}")
def final_settlement_detail(
    settlement_id: int, request: Request,
    user: User = Depends(core.require_roles("administrador", "contador", "auxiliar", "empresa", "abogado")),
    db: Session = Depends(core.get_db),
):
    settlement, exit_record, employee = _allowed_settlement(db, user, settlement_id)
    calc = db.get(CalculationRecord, settlement.calculation_record_id) if settlement.calculation_record_id else None
    return core.render(
        request, "final_settlement.html", db, user, settlement=settlement,
        exit_record=exit_record, employee=employee, calculation=calc,
        reason_label=EXIT_REASONS.get(exit_record.reason, exit_record.reason),
        documents=list(db.scalars(select(Document).where(
            Document.employee_id == employee.id,
            Document.category.in_(("Respaldo de egreso", "Comprobante de liquidación final")),
        ).order_by(Document.created_at.desc()))),
    )

@router.post("/app/final-settlements/{settlement_id}/review")
def settle_review(
    settlement_id: int,
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    settlement, exit_record, employee = _allowed_settlement(db, user, settlement_id)
    if settlement.status != "En Revisión" or not settlement.calculation_record_id:
        raise HTTPException(409, "La liquidación debe encontrarse calculada y en revisión.")
    calc = db.get(CalculationRecord, settlement.calculation_record_id)
    if not calc or calc.calculation_type != "suite_settlement" or calc.employee_id != employee.id or calc.company_id != employee.company_id:
        raise HTTPException(409, "El cálculo asociado no corresponde a este egreso.")
    # Revalidate persisted calculations against the current professional engine.
    core._revalidate_calculation_before_approval(calc, db)
    if int(calc.amount) < 0:
        raise HTTPException(409, "El cálculo tiene un importe neto inválido.")
    calc.status = "Aprobado"
    settlement.approved_amount = int(calc.amount)
    settlement.calculated_amount = int(calc.amount)
    settlement.approved_by = user.email
    settlement.approved_at = datetime.now(UTC)
    settlement.status = "Aprobada"
    core.add_employee_event(db, employee, user, "Liquidación", "Liquidación final aprobada",
                            f"Procedimiento #{exit_record.id}; liquidación #{settlement.id}; cálculo #{calc.id}.",
                            current_paraguay_date(), int(calc.amount))
    core.write_audit(db, user, "aprobar_liquidacion_final", "liquidacion_final", str(settlement.id), f"Cálculo #{calc.id}; Gs. {calc.amount}")
    db.commit()
    return RedirectResponse(f"/app/final-settlements/{settlement.id}", status_code=303)

@router.post("/app/final-settlements/{settlement_id}/payment")
async def settle_payment(
    settlement_id: int,
    payment_date: date = Form(...),
    payment_amount: int = Form(...),
    payment_method: str = Form(...),
    payment_reference: str = Form(""),
    receipt: UploadFile = File(...),
    user: User = Depends(core.require_roles("administrador", "contador")),
    db: Session = Depends(core.get_db),
):
    settlement, exit_record, employee = _allowed_settlement(db, user, settlement_id)
    if settlement.status != "Aprobada" or settlement.approved_amount is None:
        raise HTTPException(409, "Solo una liquidación aprobada puede registrarse como pagada.")
    if payment_amount != settlement.approved_amount or payment_amount < 0:
        raise HTTPException(422, "El pago total debe coincidir con el importe aprobado. No se permiten pagos parciales en este flujo.")
    if payment_date > current_paraguay_date():
        raise HTTPException(422, "No se puede registrar un pago de fecha futura.")
    if not payment_method.strip() or len(payment_method) > 80 or len(payment_reference) > 180:
        raise HTTPException(422, "Indicá un medio de pago válido y una referencia de hasta 180 caracteres.")
    document = await _attach_document(
        db, employee, user, receipt, "Comprobante de liquidación final",
        f"Pago liquidación #{settlement.id} · {payment_date.isoformat()}",
    )
    db.flush()
    settlement.receipt_document_id = document.id
    settlement.payment_date = payment_date
    settlement.payment_amount = payment_amount
    settlement.payment_method = payment_method.strip()
    settlement.payment_reference = payment_reference.strip()
    settlement.paid_by = user.email
    settlement.paid_at = datetime.now(UTC)
    settlement.status = "Pagada"
    core.add_employee_event(db, employee, user, "Liquidación", "Liquidación final pagada",
                            f"Liquidación #{settlement.id}; comprobante documento #{document.id}; medio: {payment_method.strip()}.",
                            payment_date, payment_amount)
    core.write_audit(db, user, "registrar_pago_liquidacion", "liquidacion_final", str(settlement.id), f"Gs. {payment_amount}; comprobante #{document.id}")
    db.commit()
    return RedirectResponse(f"/app/final-settlements/{settlement.id}", status_code=303)
