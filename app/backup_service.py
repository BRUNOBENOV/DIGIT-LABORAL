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
    Document,
    Employee,
    EmployeeEvent,
    LaborDeadline,
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
                        "requests": len(requests), "documents": len(documents), "deadlines": len(deadlines),
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
        _write_csv(archive, "datos/agenda.csv", ["id", "empresa_id", "funcionario_id", "titulo", "tipo", "fecha", "prioridad", "estado", "notas"], ((x.id, x.company_id, x.employee_id, x.title, x.deadline_type, x.due_date, x.priority, x.status, x.notes) for x in deadlines))
        _write_csv(archive, "datos/auditoria.csv", ["fecha", "usuario", "accion", "entidad", "entidad_id", "detalle"], ((x.created_at, x.user_email, x.action, x.entity, x.entity_id, x.detail) for x in audit))

        for item in documents:
            source = upload_dir / item.stored_name
            if source.is_file():
                archive.write(source, f"archivos/documentos/{item.company_id}/{item.id}_{item.original_name}")
        for item in attachments:
            source = upload_dir / "requests" / str(item.request_id) / item.stored_name
            if source.is_file():
                archive.write(source, f"archivos/solicitudes/{item.request_id}/{item.id}_{item.original_name}")
    return output.getvalue()
