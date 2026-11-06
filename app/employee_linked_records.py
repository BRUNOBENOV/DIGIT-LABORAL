"""Read-only, tenant-scoped index of records preventing employee deletion.

Only whitelisted, lightweight columns are selected: never fetch document blobs,
certificate bodies, model responses, or unbounded JSON payloads.
"""
from urllib.parse import urlencode

from sqlalchemy import func, or_, select

from .employee_deletion import LABELS, employee_references


# Fields are inspected against each SQLAlchemy Table, not interpolated into SQL.
SAFE_COLUMNS = (
    "id", "title", "status", "calculation_type", "reference_period", "amount",
    "document_type", "issue_date", "created_at", "effective_date", "event_date",
    "event_type", "authority", "period_year", "operation_type", "purpose",
    "category", "original_name", "payroll_id", "company_id", "employee_id",
    "source", "period", "name", "type", "due_date", "start_date", "end_date",
)
CALCULATION_NAMES = {
    "salary": "Liquidación de salario", "suite_salary": "Liquidación de salario",
    "aguinaldo": "Aguinaldo", "vacation": "Vacaciones", "notice": "Preaviso",
    "hours": "Horas trabajadas",
}
FIELD_NAMES = {
    "status": "Estado", "reference_period": "Período", "amount": "Importe",
    "issue_date": "Emisión", "created_at": "Registrado",
    "effective_date": "Fecha efectiva", "event_date": "Fecha",
    "period_year": "Año", "authority": "Autoridad",
    "period": "Período", "due_date": "Vencimiento", "source": "Origen",
    "category": "Categoría",
}


def _short(value, limit=150):
    if value is None or value == "":
        return ""
    result = str(value).replace("\n", " ").replace("\r", " ").strip()
    return result if len(result) <= limit else result[: limit - 1] + "…"


def _record_link(table_name, row, employee):
    record_id = row.get("id")
    if record_id is None:
        return None
    if table_name == "calculation_records":
        kind = row.get("calculation_type")
        if kind in {"salary", "suite_salary"}:
            return f"/app/reports/liquidaciones-salarios/{record_id}"
        if kind in {"aguinaldo", "suite_aguinaldo"}:
            return f"/app/reports/liquidaciones-aguinaldo/calculo/{record_id}"
        if kind:
            return "/app/calculations?" + urlencode({
                "tipo": kind, "saved": record_id, "company_id": employee.company_id, "employee_id": employee.id,
            })
    direct = {
        "generated_certificates": f"/app/certificates/{record_id}/print",
        "aguinaldos": f"/app/reports/liquidaciones-aguinaldo/registro/{record_id}",
        "documents": f"/app/documents/{record_id}/download",
        "payroll_lines": f"/app/payrolls/{row['payroll_id']}" if row.get("payroll_id") else None,
        "vacations": f"/app/vacations/{record_id}",
        "final_settlements": f"/app/final-settlements/{record_id}",
        "employee_exits": f"/app/employees/{employee.id}",
    }
    return direct.get(table_name)


def _display_row(table_name, row, employee):
    record_id = row.get("id", "—")
    label = LABELS.get(table_name, "Registro vinculado")
    kind = row.get("calculation_type")
    title = row.get("title") or row.get("name") or row.get("original_name")
    if table_name == "calculation_records":
        title = CALCULATION_NAMES.get(kind, kind or "Cálculo")
    elif table_name == "generated_certificates":
        title = row.get("title") or row.get("document_type") or "Certificado"
    elif table_name == "ai_interactions":
        title = row.get("purpose") or "Consulta del asistente"
    elif not title:
        title = row.get("document_type") or row.get("operation_type") or row.get("event_type") or label

    summary = []
    for field in ("status", "reference_period", "period", "amount", "issue_date", "effective_date",
                  "event_date", "period_year", "authority", "source", "category", "created_at"):
        value = row.get(field)
        if value is None or value == "":
            continue
        if field == "amount":
            value = "Gs. " + f"{value:,.0f}".replace(",", ".")
        elif hasattr(value, "isoformat"):
            value = value.isoformat()[:19].replace("T", " ")
        summary.append(f"{FIELD_NAMES[field]}: {_short(value, 60)}")
        if len(summary) == 4:
            break
    return {
        "id": record_id,
        "title": _short(title, 120),
        "subtitle": " · ".join(summary),
        "url": _record_link(table_name, row, employee),
    }


def linked_record_page(db, employee, category, *, page=1, page_size=25):
    """List one referenced table with bounded pagination; no cross-tenant rows."""
    references = {table.name: (table, columns) for table, columns in employee_references()}
    if category not in references:
        raise KeyError(category)
    table, columns = references[category]
    clause = or_(*(column == employee.id for column in columns))
    total = db.scalar(select(func.count()).select_from(table).where(clause)) or 0
    page_size = max(1, min(int(page_size), 25))
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(int(page), pages))
    selected = [table.c[name] for name in SAFE_COLUMNS if name in table.c]
    if category == "ai_interactions":
        # Return only a short preview of the prompt; never load full transcripts.
        if "user_instruction" in table.c:
            selected.append(func.substr(table.c.user_instruction, 1, 170).label("prompt_preview"))
    order = table.c.id.desc() if "id" in table.c else list(table.primary_key.columns)[0].desc()
    rows = db.execute(select(*selected).where(clause).order_by(order).limit(page_size).offset((page - 1) * page_size)).mappings()
    items = []
    for row in rows:
        item = _display_row(category, row, employee)
        if category == "ai_interactions" and row.get("prompt_preview"):
            item["subtitle"] += (" · " if item["subtitle"] else "") + "Consulta: " + _short(row["prompt_preview"], 160)
        items.append(item)
    return {
        "key": category, "label": LABELS.get(category, "Otros registros vinculados"),
        "total": total, "page": page, "pages": pages, "items": items,
    }
