"""Add company maintenance fields and backfill numeric codes.

Revision ID: 0015_company_maintenance_fields
Revises: 0014_tenant_user_context
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0015_company_maintenance_fields"
down_revision = "0014_tenant_user_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("companies")}
    additions = [
        ("company_code", sa.Column("company_code", sa.Integer(), nullable=True)),
        ("owner_name", sa.Column("owner_name", sa.String(length=180), nullable=False, server_default="")),
        ("work_sector", sa.Column("work_sector", sa.String(length=160), nullable=False, server_default="")),
        ("work_location", sa.Column("work_location", sa.String(length=180), nullable=False, server_default="")),
        ("contact_name", sa.Column("contact_name", sa.String(length=180), nullable=False, server_default="")),
        ("updated_at", sa.Column("updated_at", sa.DateTime(), nullable=True)),
    ]
    for name, column in additions:
        if name not in columns:
            op.add_column("companies", column)

    rows = bind.execute(sa.text(
        "SELECT id, studio_id, company_code, created_at, updated_at FROM companies ORDER BY studio_id, id"
    )).mappings().all()
    used: dict[int, set[int]] = {}
    highest: dict[int, int] = {}
    for row in rows:
        studio_id = int(row["studio_id"])
        used.setdefault(studio_id, set())
        if row["company_code"] is not None:
            code = int(row["company_code"])
            used[studio_id].add(code)
            highest[studio_id] = max(highest.get(studio_id, 0), code)
    for row in rows:
        studio_id = int(row["studio_id"])
        if row["company_code"] is None:
            code = highest.get(studio_id, 0) + 1
            while code in used[studio_id]:
                code += 1
            bind.execute(
                sa.text("UPDATE companies SET company_code = :code WHERE id = :company_id"),
                {"code": code, "company_id": row["id"]},
            )
            used[studio_id].add(code)
            highest[studio_id] = code
        if row["updated_at"] is None:
            bind.execute(
                sa.text("UPDATE companies SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP) WHERE id = :company_id"),
                {"company_id": row["id"]},
            )

    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("companies")}
    constraints = {item.get("name") for item in inspector.get_unique_constraints("companies")}
    if "uq_company_code_per_studio" not in indexes and "uq_company_code_per_studio" not in constraints:
        op.create_index("uq_company_code_per_studio", "companies", ["studio_id", "company_code"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("companies")}
    if "uq_company_code_per_studio" in indexes:
        op.drop_index("uq_company_code_per_studio", table_name="companies")
    columns = {item["name"] for item in sa.inspect(bind).get_columns("companies")}
    for name in ("updated_at", "contact_name", "work_location", "work_sector", "owner_name", "company_code"):
        if name in columns:
            op.drop_column("companies", name)
