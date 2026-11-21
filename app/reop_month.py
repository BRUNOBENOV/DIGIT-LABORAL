"""Persist reviewed choices independently of the approved salaries."""
from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .models import IntegrationBatch, ReopSalaryMonth
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
