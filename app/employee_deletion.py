"""Permanent deletion with explicit references and a signed review."""
import hashlib
import json
from urllib.parse import parse_qsl, urlencode, urlsplit
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import delete, func, literal, or_, select, union_all
from .config import settings
from .database import Base
from .models import Employee

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


def deletion_preview(db, employee, *, lock_profile=False):
    refs = employee_references()
    counts = dict(db.execute(union_all(*[
        select(literal(t.name), func.count()).select_from(t).where(or_(*(c == employee.id for c in columns)))
        for t, columns in refs
    ])).all())
    profile, blockers = [], []
    snapshot = {"employee": {c.name: getattr(employee, c.name) for c in Employee.__table__.columns}, "counts": counts, "profile": {}}
    for table, columns in refs:
        count = counts[table.name]
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
            "fingerprint": fingerprint, "confirmation": f"ELIMINAR {code}"}


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


def remove_dossier(db, employee):
    # Core DELETE avoids implicit ORM nullification. Existing FKs remain the
    # last guard against concurrent or unmodeled references.
    for table, columns in employee_references():
        if is_profile_reference(table, columns):
            db.execute(delete(table).where(or_(*(c == employee.id for c in columns))))
    result = db.execute(delete(Employee.__table__).where(Employee.id == employee.id))
    if result.rowcount != 1:
        raise DeletionConflict("La base no autorizó la eliminación del registro.")
