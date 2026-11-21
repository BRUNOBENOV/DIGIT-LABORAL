"""Persist reviewed choices independently of the approved salaries."""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import defer
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .models import Employee, IntegrationBatch, ReopSalaryMonth
from .reop_ledger import doc_key
from .salary_data import object_json


def read_month(db, company_id, period):
    return db.get(ReopSalaryMonth, (company_id, period))


def lock_month(db, company_id, period):
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
    db.execute(insert(ReopSalaryMonth).values(company_id=company_id, period=period, payments={}, snapshots={})
               .on_conflict_do_nothing(index_elements=["company_id", "period"]))
    return db.scalar(select(ReopSalaryMonth).where(ReopSalaryMonth.company_id == company_id,
                     ReopSalaryMonth.period == period).with_for_update().execution_options(populate_existing=True))


def payment_settings(db, company_id, period, month, employee_id=None):
    if month and month.payments:
        return month.payments
    # Also recover choices made before the monthly review was introduced.
    query = select(IntegrationBatch.payload_json).where(
        IntegrationBatch.company_id == company_id, IntegrationBatch.period == period,
        IntegrationBatch.authority == "REOP", IntegrationBatch.batch_type == "Importación de salarios"
    ).order_by(IntegrationBatch.id.desc())
    for raw in db.scalars(query):
        payload = object_json(raw)
        if payload.get("employee_scope_id") in (None, employee_id) and payload.get("payment_code"):
            return {"default": payload["payment_code"], "overrides": payload.get("payment_overrides", {}),
                    "apply_group": bool(payload.get("apply_group"))}
    return {"default": "auto", "overrides": {}}


def submitted_documents(db, company_id, period, storage):
    """An importer can finish before the official listing publishes the rows."""
    keys = set()
    batches = db.scalars(select(IntegrationBatch).options(
        defer(IntegrationBatch.file_bytes), defer(IntegrationBatch.receipt_bytes)
    ).where(IntegrationBatch.company_id == company_id, IntegrationBatch.period == period,
            IntegrationBatch.authority == "REOP", IntegrationBatch.batch_type == "Importación de salarios",
            IntegrationBatch.status != "Rechazado"))
    for batch in batches:
        data = object_json(batch.payload_json)
        if batch.status not in {"Presentado", "Aceptado"} and (data.get("assistant_progress") or {}).get("phase") != "imported":
            continue
        if data.get("reop_documents"):
            keys.update((str(patronal), doc_key(document)) for patronal, document in data["reop_documents"])
            continue
        # Older lots predate the document index. Their archived Excel identifies
        # exactly who was sent, including partial and single-worker lots.
        try:
            content = batch.file_bytes or storage.get(batch.storage_key)
            if sha256(content).hexdigest() != batch.file_sha256:
                raise ValueError("Archivo incompleto")
            book = load_workbook(BytesIO(content), read_only=True, data_only=True)
            try:
                rows = list(book.active.iter_rows(min_row=2, max_col=2, values_only=True))
            finally:
                book.close()
            if len(rows) != batch.item_count or not all(p and d for p, d in rows):
                raise ValueError("No se identificaron todas las filas")
            keys.update((str(p), doc_key(d)) for p, d in rows)
        except Exception:
            # Without a readable receipt workbook the affected scope needs a
            # portal review. Never interpret its absence as permission to resend.
            employee_id = data.get("employee_scope_id")
            ci = db.scalar(select(Employee.document_number).where(Employee.id == employee_id,
                           Employee.company_id == company_id)) if employee_id else None
            keys.add(("*", doc_key(ci) if ci else "*"))
    return keys
