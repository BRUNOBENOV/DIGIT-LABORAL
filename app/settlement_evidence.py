"""Bind a declared judicial exception to an existing, scoped employee document."""
from __future__ import annotations

import hashlib

from sqlalchemy import select

from .labor_calculator import CalculationError, checked
from .models import Document
from .storage_service import storage


def document_id(value):
    raw = str(value or "")
    return int(raw) if raw.isascii() and raw.isdigit() and len(raw) <= 10 and 0 < int(raw) <= 2147483647 else None


def judicial_document_choices(db, employee, selected_id=None):
    base = select(Document.id, Document.title, Document.original_name).where(
        Document.company_id == employee.company_id, Document.employee_id == employee.id,
        Document.content_type.in_(("application/pdf", "image/png", "image/jpeg")),
    )
    rows = list(db.execute(base.order_by(Document.id.desc()).limit(50)))
    chosen = document_id(selected_id)
    if chosen and not any(row.id == chosen for row in rows):
        rows.extend(db.execute(base.where(Document.id == chosen)))
    return [dict(id=row.id, label=f"#{row.id} · {row.title} · {row.original_name}") for row in rows]


def verify_judicial_document(db, employee, data):
    if data.get("kind") != "settlement" or not checked(data, "judicial_confirmed"):
        data.pop("judicial_document_sha256", None)
        return None
    chosen = document_id(data.get("judicial_document_id"))
    if not employee or not chosen:
        raise CalculationError("Adjuntá la sentencia en Documentos y seleccioná el archivo de este funcionario.", "judicial_document_id")
    document = db.get(Document, chosen)
    if (not document or document.company_id != employee.company_id or document.employee_id != employee.id
            or document.content_type not in {"application/pdf", "image/png", "image/jpeg"}):
        raise CalculationError("Seleccioná una sentencia PDF o imagen del expediente de este funcionario y empresa.", "judicial_document_id")
    try:
        content = bytes(document.content_bytes) if document.content_bytes is not None else storage.get(document.stored_name)
    except Exception as exc:
        raise CalculationError("El archivo adjunto no está disponible. Volvé a adjuntarlo antes de calcular.", "judicial_document_id") from exc
    if not content or len(content) > 10 * 1024 * 1024:
        raise CalculationError("El respaldo está vacío o supera 10 MB. Revisá el archivo adjunto.", "judicial_document_id")
    sha256 = hashlib.sha256(content).hexdigest()
    if data.get("judicial_document_sha256") and data["judicial_document_sha256"] != sha256:
        raise CalculationError("Cambió el archivo judicial utilizado. Revisá y seleccioná nuevamente el respaldo.", "judicial_document_id")
    data["judicial_document_sha256"] = sha256
    return dict(document_id=document.id, company_id=document.company_id, employee_id=document.employee_id,
                title=document.title, original_name=document.original_name, sha256=sha256,
                reference=str(data.get("judicial_reference", "")), judgment_date=str(data.get("judicial_date", "")))


def annotate_judicial_document(result, evidence):
    if evidence:
        result["judicial_provenance"] = evidence
        result["facts"].append(dict(label="Respaldo judicial adjunto", value=f"Documento #{evidence['document_id']} · {evidence['original_name']}"))
        result["notes"].append("Huella del archivo judicial: " + evidence["sha256"] + ". La vinculación del archivo no acredita su autenticidad, firmeza ni procedencia; requiere revisión profesional.")
    return result
