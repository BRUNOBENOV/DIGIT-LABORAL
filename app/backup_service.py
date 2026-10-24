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

from .storage_service import storage
from .models import (
    AuditLog,
    Company,
    CompanyRequest,
    ComplianceEvent,
    Document,
    IntegrationBatch,
    IntegrationBatchItem,
    Employee,
    EmployeeEvent,
    LaborDeadline,
    OfficialCertificateRecord,
    RequestAttachment,
    RequestComment,
    RequestWorkflow,
    SalaryHistory,
    Studio,
    User,
)


def _plain(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _write_csv(archive: zipfile.ZipFile, name: str, headers: list[str], rows: Iterable[Iterable[Any]]) -> None:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_plain(value) for value in row])
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
    documents = list(db.scalars(select(Document).where(Document.company_id.in_(company_ids)))) if company_ids else []
    official_certificates = list(db.scalars(select(OfficialCertificateRecord).where(OfficialCertificateRecord.company_id.in_(company_ids)).order_by(OfficialCertificateRecord.id))) if company_ids else []
    compliance_events = list(db.scalars(select(ComplianceEvent).where(ComplianceEvent.company_id.in_(company_ids)).order_by(ComplianceEvent.id))) if company_ids else []
    integration_batches = list(db.scalars(select(IntegrationBatch).where(IntegrationBatch.company_id.in_(company_ids)).order_by(IntegrationBatch.id))) if company_ids else []
    integration_batch_ids = [item.id for item in integration_batches]
    integration_batch_items = list(db.scalars(select(IntegrationBatchItem).where(IntegrationBatchItem.batch_id.in_(integration_batch_ids)).order_by(IntegrationBatchItem.id))) if integration_batch_ids else []
    events = list(db.scalars(select(EmployeeEvent).where(EmployeeEvent.employee_id.in_(employee_ids)))) if employee_ids else []
    salaries = list(db.scalars(select(SalaryHistory).where(SalaryHistory.employee_id.in_(employee_ids)))) if employee_ids else []
    deadlines = list(db.scalars(select(LaborDeadline).where(LaborDeadline.company_id.in_(company_ids)))) if company_ids else []
    audit = list(db.scalars(select(AuditLog).where(AuditLog.studio_id == studio.id).order_by(AuditLog.id)))

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "product": "Digit Laboral",
                    "schema": "studio-export-v1",
                    "studio": {"id": studio.id, "name": studio.name, "ruc": studio.ruc, "plan": studio.plan_name},
                    "counts": {
                        "companies": len(companies), "employees": len(employees), "users": len(users),
                        "requests": len(requests), "documents": len(documents), "official_certificates": len(official_certificates), "deadlines": len(deadlines),
                        "compliance_events": len(compliance_events), "integration_batches": len(integration_batches),
                        "integration_batch_items": len(integration_batch_items),
                    },
                    "note": "No incluye contraseñas, secretos de doble factor ni tokens.",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        _write_csv(archive, "datos/empresas.csv", ["id", "razon_social", "nombre_comercial", "ruc", "ciudad", "direccion", "telefono", "correo", "estado"], ((x.id, x.legal_name, x.trade_name, x.ruc, x.city, x.address, x.phone, x.email, x.status) for x in companies))
        _write_csv(archive, "datos/funcionarios.csv", ["id", "empresa_id", "nombre", "cedula", "cargo", "ingreso", "salario", "ips", "estado", "salida"], ((x.id, x.company_id, x.full_name, x.document_number, x.position, x.admission_date, x.base_salary, x.ips_contributor, x.status, x.termination_date) for x in employees))
        _write_csv(archive, "datos/usuarios.csv", ["id", "nombre", "correo", "rol", "empresa_id", "activo", "ultimo_acceso"], ((x.id, x.full_name, x.email, x.role, x.company_id, x.active, x.last_login_at) for x in users))
        _write_csv(archive, "datos/solicitudes.csv", ["id", "empresa_id", "tipo", "asunto", "prioridad", "estado", "creada", "resuelta"], ((x.id, x.company_id, x.request_type, x.subject, x.priority, x.status, x.created_at, x.resolved_at) for x in requests))
        _write_csv(archive, "datos/flujo_solicitudes.csv", ["solicitud_id", "responsable_usuario_id", "fecha_limite", "notas_internas"], ((x.request_id, x.assigned_user_id, x.due_date, x.internal_notes) for x in workflows))
        _write_csv(archive, "datos/comentarios_solicitudes.csv", ["solicitud_id", "autor", "visibilidad", "comentario", "fecha"], ((x.request_id, x.author_name, x.visibility, x.body, x.created_at) for x in comments))
        _write_csv(archive, "datos/eventos_funcionarios.csv", ["funcionario_id", "tipo", "titulo", "detalle", "fecha_efectiva", "monto", "creado_por"], ((x.employee_id, x.event_type, x.title, x.detail, x.effective_date, x.amount, x.created_by) for x in events))
        _write_csv(archive, "datos/historial_salarial.csv", ["funcionario_id", "salario_anterior", "salario_nuevo", "vigente_desde", "motivo", "creado_por"], ((x.employee_id, x.previous_salary, x.new_salary, x.effective_from, x.reason, x.created_by) for x in salaries))
        _write_csv(archive, "datos/certificados_oficiales.csv", ["id", "empresa_id", "funcionario_id", "institucion", "tipo", "estado", "fecha_solicitud", "fecha_emision", "fecha_vencimiento", "numero_oficial", "resultado", "documento_id", "notas", "creado_por", "actualizado_por", "creado", "actualizado"], ((x.id, x.company_id, x.employee_id, x.institution, x.certificate_type, x.status, x.request_date, x.issue_date, x.expiry_date, x.official_number, x.result_status, x.document_id, x.notes, x.created_by, x.updated_by, x.created_at, x.updated_at) for x in official_certificates))
        _write_csv(archive, "datos/comunicaciones_cumplimiento.csv", ["id", "empresa_id", "funcionario_id", "sucursal_id", "lote_id", "autoridad", "tipo", "fecha", "fecha_limite", "estado", "clave_origen", "payload_json", "referencia_externa", "notas", "creado_por", "aprobado_por", "presentado", "creado"], ((x.id, x.company_id, x.employee_id, x.branch_id, x.batch_id, x.authority, x.event_type, x.event_date, x.due_date, x.status, x.source_key, x.payload_json, x.external_reference, x.notes, x.created_by, x.approved_by, x.submitted_at, x.created_at) for x in compliance_events))
        _write_csv(archive, "datos/lotes_integracion.csv", ["id", "empresa_id", "autoridad", "tipo", "periodo", "estado", "nombre_archivo", "storage_key", "sha256", "registros", "referencia_externa", "error", "creado_por", "aprobado_por", "presentado", "creado"], ((x.id, x.company_id, x.authority, x.batch_type, x.period, x.status, x.file_name, x.storage_key, x.file_sha256, x.item_count, x.external_reference, x.error_message, x.created_by, x.approved_by, x.submitted_at, x.created_at) for x in integration_batches))
        _write_csv(archive, "datos/lotes_integracion_items.csv", ["id", "lote_id", "comunicacion_id", "estado", "respuesta"], ((x.id, x.batch_id, x.compliance_event_id, x.status, x.response_message) for x in integration_batch_items))
        _write_csv(archive, "datos/agenda.csv", ["id", "empresa_id", "funcionario_id", "titulo", "tipo", "fecha", "prioridad", "estado", "notas"], ((x.id, x.company_id, x.employee_id, x.title, x.deadline_type, x.due_date, x.priority, x.status, x.notes) for x in deadlines))
        _write_csv(archive, "datos/auditoria.csv", ["fecha", "usuario", "accion", "entidad", "entidad_id", "detalle"], ((x.created_at, x.user_email, x.action, x.entity, x.entity_id, x.detail) for x in audit))

        for item in documents:
            archive_name = f"archivos/documentos/{item.company_id}/{item.id}_{item.original_name}"
            if item.content_bytes is not None:
                archive.writestr(archive_name, bytes(item.content_bytes))
                continue
            if storage.exists(item.stored_name):
                archive.writestr(archive_name, storage.get(item.stored_name))
                continue
            source = upload_dir / item.stored_name
            if source.is_file():
                archive.write(source, archive_name)
        for item in attachments:
            archive_name = f"archivos/solicitudes/{item.request_id}/{item.id}_{item.original_name}"
            if item.content_bytes is not None:
                archive.writestr(archive_name, bytes(item.content_bytes))
                continue
            if storage.exists(item.stored_name):
                archive.writestr(archive_name, storage.get(item.stored_name))
                continue
            legacy_candidates = (
                upload_dir / item.stored_name,
                upload_dir / "requests" / str(item.request_id) / Path(item.stored_name).name,
            )
            source = next((candidate for candidate in legacy_candidates if candidate.is_file()), None)
            if source is not None:
                archive.write(source, archive_name)

        for batch in integration_batches:
            batch_name = Path(batch.file_name or f"lote-{batch.id}.xlsx").name
            archive_name = f"archivos/integraciones/{batch.company_id}/lotes/{batch.id}_{batch_name}"
            if batch.file_bytes is not None:
                archive.writestr(archive_name, bytes(batch.file_bytes))
            elif batch.storage_key and storage.exists(batch.storage_key):
                archive.writestr(archive_name, storage.get(batch.storage_key))
            elif batch.storage_key:
                source = upload_dir / batch.storage_key
                if source.is_file():
                    archive.write(source, archive_name)

            receipt_key = batch.receipt_storage_key or next(
                (event.receipt_storage_key for event in compliance_events
                 if event.batch_id == batch.id and event.receipt_storage_key),
                "",
            )
            receipt_name = Path(batch.receipt_file_name or (Path(receipt_key).name if receipt_key else f"comprobante-{batch.id}")).name
            receipt_archive_name = f"archivos/integraciones/{batch.company_id}/comprobantes/{batch.id}_{receipt_name}"
            if batch.receipt_bytes is not None:
                archive.writestr(receipt_archive_name, bytes(batch.receipt_bytes))
            elif receipt_key and storage.exists(receipt_key):
                archive.writestr(receipt_archive_name, storage.get(receipt_key))
            elif receipt_key:
                source = upload_dir / receipt_key
                if source.is_file():
                    archive.write(source, receipt_archive_name)
    return output.getvalue()
