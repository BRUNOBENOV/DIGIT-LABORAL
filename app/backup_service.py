from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AuditLog,
    Company,
    CompanyRequest,
    ComplianceEvent,
    Document,
    Employee,
    EmployeeEvent,
    IntegrationBatch,
    IntegrationBatchItem,
    LaborDeadline,
    OfficialCertificateRecord,
    RequestAttachment,
    RequestComment,
    RequestWorkflow,
    SalaryHistory,
    Studio,
    User,
)
from .storage_service import storage


def _plain(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _safe_csv_cell(value: Any) -> Any:
    """Neutralize spreadsheet formulas in text values included in a ZIP backup."""
    value = _plain(value)
    if not isinstance(value, str):
        return value
    trimmed = value.lstrip(" \t\r\n")
    if value.startswith(("\t", "\r", "\n")) or (trimmed and trimmed[0] in {"=", "+", "-", "@"}):
        return "'" + value
    return value


def _safe_archive_component(value: str | None, fallback: str) -> str:
    """Make an untrusted uploaded filename a single safe ZIP path component."""
    candidate = str(value or "").replace("\\", "/").split("/")[-1]
    candidate = "".join(ch if ord(ch) >= 32 and ord(ch) != 127 else "_" for ch in candidate)
    candidate = candidate.strip().strip(". ").rstrip(". ")
    if not candidate or candidate in {".", ".."}:
        candidate = fallback
    return candidate[:180].rstrip(". ") or fallback


def _read_stored_object(key: str, upload_dir: Path) -> bytes | None:
    """Read a stored object from the configured backend or a validated legacy upload path."""
    if not key:
        return None
    if storage.exists(key):
        # If the configured provider reports the object, surface read errors so a backup
        # cannot silently claim completeness when an existing object cannot be copied.
        return bytes(storage.get(key))
    root = upload_dir.resolve()
    candidate = (root / key).resolve()
    if candidate == root or root not in candidate.parents:
        return None
    if candidate.is_file():
        return candidate.read_bytes()
    return None


def _write_csv(archive: zipfile.ZipFile, name: str, headers: list[str], rows: Iterable[Iterable[Any]]) -> None:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_safe_csv_cell(value) for value in row])
    archive.writestr(name, "\ufeff" + output.getvalue())


def build_studio_export(db: Session, studio: Studio, upload_dir: Path) -> bytes:
    companies = list(db.scalars(select(Company).where(Company.studio_id == studio.id).order_by(Company.id)))
    company_ids = [item.id for item in companies]
    employees = list(db.scalars(select(Employee).where(Employee.company_id.in_(company_ids)).order_by(Employee.id))) if company_ids else []
    employee_ids = [item.id for item in employees]
    users = list(db.scalars(select(User).where(User.studio_id == studio.id).order_by(User.id)))
    requests = list(db.scalars(select(CompanyRequest).where(CompanyRequest.company_id.in_(company_ids)).order_by(CompanyRequest.id))) if company_ids else []
    request_ids = [item.id for item in requests]
    workflows = list(db.scalars(select(RequestWorkflow).where(RequestWorkflow.request_id.in_(request_ids)))) if request_ids else []
    comments = list(db.scalars(select(RequestComment).where(RequestComment.request_id.in_(request_ids)))) if request_ids else []
    attachments = list(db.scalars(select(RequestAttachment).where(RequestAttachment.request_id.in_(request_ids)))) if request_ids else []
    documents = list(db.scalars(select(Document).where(Document.company_id.in_(company_ids)).order_by(Document.id))) if company_ids else []
    official_certificates = list(db.scalars(select(OfficialCertificateRecord).where(OfficialCertificateRecord.company_id.in_(company_ids)).order_by(OfficialCertificateRecord.id))) if company_ids else []
    compliance_events = list(db.scalars(select(ComplianceEvent).where(ComplianceEvent.company_id.in_(company_ids)).order_by(ComplianceEvent.id))) if company_ids else []
    integration_batches = list(db.scalars(select(IntegrationBatch).where(IntegrationBatch.company_id.in_(company_ids)).order_by(IntegrationBatch.id))) if company_ids else []
    batch_ids = [item.id for item in integration_batches]
    integration_batch_items = list(db.scalars(select(IntegrationBatchItem).where(IntegrationBatchItem.batch_id.in_(batch_ids)).order_by(IntegrationBatchItem.id))) if batch_ids else []
    events = list(db.scalars(select(EmployeeEvent).where(EmployeeEvent.employee_id.in_(employee_ids)))) if employee_ids else []
    salaries = list(db.scalars(select(SalaryHistory).where(SalaryHistory.employee_id.in_(employee_ids)))) if employee_ids else []
    deadlines = list(db.scalars(select(LaborDeadline).where(LaborDeadline.company_id.in_(company_ids)))) if company_ids else []
    audit = list(db.scalars(select(AuditLog).where(AuditLog.studio_id == studio.id).order_by(AuditLog.id)))

    counts = {
        "companies": len(companies),
        "employees": len(employees),
        "users": len(users),
        "requests": len(requests),
        "documents": len(documents),
        "official_certificates": len(official_certificates),
        "deadlines": len(deadlines),
        "compliance_events": len(compliance_events),
        "integration_batches": len(integration_batches),
        "integration_batch_items": len(integration_batch_items),
    }
    missing_artifacts: list[dict[str, Any]] = []
    archived_keys: set[str] = set()
    output = io.BytesIO()

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        _write_csv(archive, "datos/empresas.csv", ["id", "razon_social", "nombre_comercial", "ruc", "ciudad", "direccion", "telefono", "correo", "estado"], ((x.id, x.legal_name, x.trade_name, x.ruc, x.city, x.address, x.phone, x.email, x.status) for x in companies))
        _write_csv(archive, "datos/funcionarios.csv", ["id", "empresa_id", "nombre", "cedula", "cargo", "ingreso", "salario", "ips", "estado", "salida"], ((x.id, x.company_id, x.full_name, x.document_number, x.position, x.admission_date, x.base_salary, x.ips_contributor, x.status, x.termination_date) for x in employees))
        _write_csv(archive, "datos/usuarios.csv", ["id", "nombre", "correo", "rol", "empresa_id", "activo", "ultimo_acceso"], ((x.id, x.full_name, x.email, x.role, x.company_id, x.active, x.last_login_at) for x in users))
        _write_csv(archive, "datos/solicitudes.csv", ["id", "empresa_id", "tipo", "asunto", "prioridad", "estado", "creada", "resuelta"], ((x.id, x.company_id, x.request_type, x.subject, x.priority, x.status, x.created_at, x.resolved_at) for x in requests))
        _write_csv(archive, "datos/flujo_solicitudes.csv", ["solicitud_id", "responsable_usuario_id", "fecha_limite", "notas_internas"], ((x.request_id, x.assigned_user_id, x.due_date, x.internal_notes) for x in workflows))
        _write_csv(archive, "datos/comentarios_solicitudes.csv", ["solicitud_id", "autor", "visibilidad", "comentario", "fecha"], ((x.request_id, x.author_name, x.visibility, x.body, x.created_at) for x in comments))
        _write_csv(archive, "datos/eventos_funcionarios.csv", ["funcionario_id", "tipo", "titulo", "detalle", "fecha_efectiva", "monto", "creado_por"], ((x.employee_id, x.event_type, x.title, x.detail, x.effective_date, x.amount, x.created_by) for x in events))
        _write_csv(archive, "datos/historial_salarial.csv", ["funcionario_id", "salario_anterior", "salario_nuevo", "vigente_desde", "motivo", "creado_por"], ((x.employee_id, x.previous_salary, x.new_salary, x.effective_from, x.reason, x.created_by) for x in salaries))
        _write_csv(archive, "datos/certificados_oficiales.csv", ["id", "empresa_id", "funcionario_id", "institucion", "tipo", "estado", "fecha_solicitud", "fecha_emision", "fecha_vencimiento", "numero_oficial", "resultado", "documento_id", "notas", "creado_por", "actualizado_por", "creado", "actualizado"], ((x.id, x.company_id, x.employee_id, x.institution, x.certificate_type, x.status, x.request_date, x.issue_date, x.expiry_date, x.official_number, x.result_status, x.document_id, x.notes, x.created_by, x.updated_by, x.created_at, x.updated_at) for x in official_certificates))
        _write_csv(archive, "datos/comunicaciones_cumplimiento.csv", ["id", "empresa_id", "funcionario_id", "sucursal_id", "lote_id", "autoridad", "tipo", "fecha", "fecha_limite", "estado", "clave_origen", "payload_json", "referencia_externa", "comprobante", "notas", "creado_por", "aprobado_por", "presentado", "creado"], ((x.id, x.company_id, x.employee_id, x.branch_id, x.batch_id, x.authority, x.event_type, x.event_date, x.due_date, x.status, x.source_key, x.payload_json, x.external_reference, x.receipt_storage_key, x.notes, x.created_by, x.approved_by, x.submitted_at, x.created_at) for x in compliance_events))
        _write_csv(archive, "datos/lotes_integracion.csv", ["id", "empresa_id", "autoridad", "tipo", "periodo", "estado", "nombre_archivo", "storage_key", "sha256", "registros", "referencia_externa", "error", "creado_por", "aprobado_por", "presentado", "creado"], ((x.id, x.company_id, x.authority, x.batch_type, x.period, x.status, x.file_name, x.storage_key, x.file_sha256, x.item_count, x.external_reference, x.error_message, x.created_by, x.approved_by, x.submitted_at, x.created_at) for x in integration_batches))
        _write_csv(archive, "datos/lotes_integracion_items.csv", ["id", "lote_id", "comunicacion_id", "estado", "respuesta"], ((x.id, x.batch_id, x.compliance_event_id, x.status, x.response_message) for x in integration_batch_items))
        _write_csv(archive, "datos/agenda.csv", ["id", "empresa_id", "funcionario_id", "titulo", "tipo", "fecha", "prioridad", "estado", "notas"], ((x.id, x.company_id, x.employee_id, x.title, x.deadline_type, x.due_date, x.priority, x.status, x.notes) for x in deadlines))
        _write_csv(archive, "datos/auditoria.csv", ["fecha", "usuario", "accion", "entidad", "entidad_id", "detalle"], ((x.created_at, x.user_email, x.action, x.entity, x.entity_id, x.detail) for x in audit))

        def add_artifact(key: str, archive_name: str, artifact_type: str, record_id: int) -> None:
            if not key:
                return
            if key in archived_keys:
                return
            try:
                content = _read_stored_object(key, upload_dir)
            except Exception:
                # Do not emit a false complete backup if a configured object store
                # reports that an object exists but retrieval fails.
                raise
            if content is None:
                missing_artifacts.append({
                    "type": artifact_type,
                    "record_id": record_id,
                    "storage_key": key,
                    "archive_path": archive_name,
                })
                return
            archive.writestr(archive_name, content)
            archived_keys.add(key)

        for item in documents:
            filename = _safe_archive_component(item.original_name, f"documento-{item.id}")
            archive_name = f"archivos/documentos/{item.company_id}/{item.id}_{filename}"
            if item.content_bytes is not None:
                archive.writestr(archive_name, bytes(item.content_bytes))
            else:
                add_artifact(item.stored_name, archive_name, "documento", item.id)

        for item in attachments:
            filename = _safe_archive_component(item.original_name, f"adjunto-{item.id}")
            archive_name = f"archivos/solicitudes/{item.request_id}/{item.id}_{filename}"
            add_artifact(item.stored_name, archive_name, "adjunto_solicitud", item.id)

        for batch in integration_batches:
            filename = _safe_archive_component(batch.file_name, f"lote-{batch.id}.xlsx")
            archive_name = f"archivos/integraciones/{batch.company_id}/lotes/{batch.id}_{filename}"
            add_artifact(batch.storage_key, archive_name, "lote_integracion", batch.id)

        for event in compliance_events:
            if not event.receipt_storage_key:
                continue
            if event.batch_id:
                target_name = f"comprobante-lote-{event.batch_id}"
                target_dir = f"archivos/integraciones/{event.company_id}/comprobantes"
            else:
                target_name = f"comprobante-evento-{event.id}"
                target_dir = f"archivos/cumplimiento/{event.company_id}/comprobantes"
            filename = _safe_archive_component(event.receipt_storage_key, f"comprobante-{event.id}")
            archive_name = f"{target_dir}/{target_name}_{filename}"
            add_artifact(event.receipt_storage_key, archive_name, "comprobante_cumplimiento", event.id)

        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "product": "Digit Laboral",
                    "schema": "studio-export-v2",
                    "created_at": datetime.now().astimezone().isoformat(),
                    "studio": {"id": studio.id, "name": studio.name, "ruc": studio.ruc, "plan": studio.plan_name},
                    "counts": counts,
                    "artifacts": {
                        "expected": sum(1 for x in documents if x.content_bytes is None)
                        + len(attachments)
                        + sum(1 for x in integration_batches if x.storage_key)
                        + sum(1 for x in compliance_events if x.receipt_storage_key),
                        "archived": len(archived_keys) + sum(1 for x in documents if x.content_bytes is not None),
                        "missing": len(missing_artifacts),
                        "status": "complete" if not missing_artifacts else "incomplete",
                    },
                    "missing_artifacts": missing_artifacts,
                    "note": "No incluye contraseñas, secretos de doble factor ni tokens. Verificá artifacts.status antes de usar el ZIP como respaldo completo.",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return output.getvalue()
