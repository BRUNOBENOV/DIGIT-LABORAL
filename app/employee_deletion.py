"""Permanent deletion with explicit references and a signed review."""
import hashlib
import json
from urllib.parse import parse_qsl, urlencode, urlsplit
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import delete, func, literal, or_, select, union_all
from .config import settings
from .database import Base
from .models import ComplianceEvent, Employee, IntegrationBatchItem

PROFILE_TABLES = {"employee_compliance_profiles", "employee_events", "salary_history"}
LABELS = {
    "employee_compliance_profiles": "Datos personales y de cumplimiento", "employee_events": "Anotaciones del legajo",
    "salary_history": "Historial salarial de la ficha", "payroll_lines": "Registros en nóminas",
    "calculation_records": "Cálculos y liquidaciones", "generated_certificates": "Certificados generados",
    "official_certificates": "Certificados oficiales", "documents": "Documentos adjuntos",
    "medical_exams": "Exámenes médicos", "employee_exits": "Procedimientos de egreso",
    "final_settlements": "Liquidaciones finales", "vacations": "Vacaciones registradas",
    "aguinaldos": "Aguinaldos registrados", "company_requests": "Solicitudes vinculadas",
    "compliance_events": "Registros de cumplimiento", "labor_operations": "Operaciones laborales",
    "labor_deadlines": "Vencimientos vinculados", "ai_interactions": "Consultas del asistente vinculadas",
    "aguinaldo_receipt_details": "Datos de pago de recibos de aguinaldo",
}
REASONS = ("Carga errónea", "Registro duplicado", "Registro de prueba", "Depuración de legajo histórico", "Otro motivo")
RETURN_KEYS = {"q", "company_id", "section_id", "status_filter", "show_archived", "page", "page_size", "employee_quick", "employee_sort", "direction"}


class DeletionConflict(ValueError):
    pass


def return_url(raw, company_id, *, deleted=False):
    try:
        p = urlsplit(raw)
        if p.scheme or p.netloc or p.path != "/app/employees" or "\\" in raw or any(ord(c) < 32 for c in raw):
            p = urlsplit(f"/app/employees?company_id={company_id}")
        pairs = [(k, v) for k, v in parse_qsl(p.query) if k in RETURN_KEYS]
    except (ValueError, TypeError):
        pairs = [("company_id", str(company_id))]
    if deleted:
        pairs.append(("deleted", "1"))
    return "/app/employees?" + urlencode(pairs)


def employee_references():
    refs = []
    for table in Base.metadata.sorted_tables:
        columns = [fk.parent for fk in table.foreign_keys if fk.column.table.name == "employees"]
        if columns:
            refs.append((table, columns))
    return refs


def is_profile_reference(table, columns):
    return table.name in PROFILE_TABLES and {c.name for c in columns} == {"employee_id"}


def automatic_entry_drafts(db, employee, *, lock=False):
    query = select(ComplianceEvent.__table__).where(ComplianceEvent.employee_id == employee.id).order_by(ComplianceEvent.id)
    if lock:
        query = query.with_for_update()
    rows = [dict(row) for row in db.execute(query).mappings()]
    event_ids = [row["id"] for row in rows]
    included = set(db.scalars(select(IntegrationBatchItem.compliance_event_id).where(
        IntegrationBatchItem.compliance_event_id.in_(event_ids)))) if event_ids else set()
    allowed = []
    for row in rows:
        key = f"employee:{employee.id}:entry:{row['authority'].lower()}"
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (ValueError, TypeError):
            continue
        if (row["company_id"] == employee.company_id and row["authority"] in {"REOP", "REI"}
                and row["event_type"] == "Entrada" and row["status"] == "Borrador"
                and row["source_key"] == key and row["id"] not in included
                and not any(row[k] for k in ("batch_id", "approved_by", "submitted_at", "external_reference", "receipt_storage_key"))
                and isinstance(payload, dict) and payload.get("generated_automatically") is True
                and payload.get("employee_id") == employee.id and payload.get("source_key") == key):
            allowed.append(row)
    return allowed, len(rows)


def deletion_preview(db, employee, *, lock_profile=False):
    refs = employee_references()
    counts = dict(db.execute(union_all(*[
        select(literal(t.name), func.count()).select_from(t).where(or_(*(c == employee.id for c in columns)))
        for t, columns in refs
    ])).all())
    profile, blockers = [], []
    snapshot = {"employee": {c.name: getattr(employee, c.name) for c in Employee.__table__.columns}, "counts": counts, "profile": {}}
    entry_drafts, entry_count = automatic_entry_drafts(db, employee, lock=lock_profile)
    counts["compliance_events"] = entry_count
    if entry_drafts:
        profile.append({"key": "automatic_entry_drafts", "label": "Avisos automáticos de alta en borrador, sin exportar", "count": len(entry_drafts)})
        snapshot["automatic_entry_drafts"] = entry_drafts
    for table, columns in refs:
        count = counts[table.name] - (len(entry_drafts) if table.name == "compliance_events" else 0)
        item = {"key": table.name, "label": LABELS.get(table.name, "Otros registros vinculados"), "count": count}
        if is_profile_reference(table, columns):
            if count:
                profile.append(item)
                query = select(table).where(or_(*(c == employee.id for c in columns))).order_by(table.c.id)
                if lock_profile:
                    query = query.with_for_update()
                rows = db.execute(query).mappings()
                snapshot["profile"][table.name] = [dict(row) for row in rows]
        elif count:
            blockers.append(item)
    fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")).encode()).hexdigest()
    code = employee.employee_code if employee.employee_code is not None else f"ID-{employee.id}"
    return {"profile": profile, "blockers": blockers, "can_delete": not blockers,
            "fingerprint": fingerprint, "confirmation": f"ELIMINAR {code}", "entry_ids": [row["id"] for row in entry_drafts]}


def review_payload(user, employee, preview):
    return {"user_id": user.id, "employee_id": employee.id, "company_id": employee.company_id, "fingerprint": preview["fingerprint"]}


def confirmation_token(user, employee, preview):
    return URLSafeTimedSerializer(settings.secret_key, salt="employee-permanent-delete-v1").dumps(review_payload(user, employee, preview))


def verify_confirmation(token, user, employee, preview):
    try:
        recorded = URLSafeTimedSerializer(settings.secret_key, salt="employee-permanent-delete-v1").loads(token, max_age=900)
    except (BadData, ValueError, TypeError):
        return False
    return recorded == review_payload(user, employee, preview)


def remove_dossier(db, employee, *, entry_ids=()):
    # Core DELETE avoids implicit ORM nullification. Existing FKs remain the
    # last guard against concurrent or unmodeled references.
    if entry_ids:
        db.execute(delete(ComplianceEvent.__table__).where(ComplianceEvent.employee_id == employee.id, ComplianceEvent.id.in_(entry_ids)))
    for table, columns in employee_references():
        if is_profile_reference(table, columns):
            db.execute(delete(table).where(or_(*(c == employee.id for c in columns))))
    result = db.execute(delete(Employee.__table__).where(Employee.id == employee.id))
    if result.rowcount != 1:
        raise DeletionConflict("La base no autorizó la eliminación del registro.")
