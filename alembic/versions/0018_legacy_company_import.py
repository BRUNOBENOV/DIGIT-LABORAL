"""Preserve legacy company identifiers and support incomplete historical RUCs.

Revision ID: 0018_legacy_company_import
Revises: 0017_reop_salary_submission
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_legacy_company_import"
down_revision = "0017_reop_salary_submission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("companies")}
    additions = [
        ("legacy_code", sa.Column("legacy_code", sa.String(length=50), nullable=True)),
        ("legacy_ruc", sa.Column("legacy_ruc", sa.String(length=40), nullable=True)),
        ("legacy_source_file", sa.Column("legacy_source_file", sa.String(length=240), nullable=True)),
        ("legacy_source_row", sa.Column("legacy_source_row", sa.Integer(), nullable=True)),
        ("legacy_source_data", sa.Column("legacy_source_data", sa.JSON(), nullable=True)),
    ]
    for name, column in additions:
        if name not in columns:
            op.add_column("companies", column)

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("companies")}
    if "uq_company_ruc_per_studio" in indexes:
        op.drop_index("uq_company_ruc_per_studio", table_name="companies")
    op.create_index(
        "uq_company_ruc_per_studio",
        "companies",
        ["studio_id", "ruc"],
        unique=True,
        postgresql_where=sa.text("ruc IS NOT NULL AND btrim(ruc) <> ''"),
    )
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("companies")}
    if "uq_company_legacy_code_per_studio" not in indexes:
        op.create_index(
            "uq_company_legacy_code_per_studio",
            "companies",
            ["studio_id", "legacy_code"],
            unique=True,
            postgresql_where=sa.text("legacy_code IS NOT NULL AND btrim(legacy_code) <> ''"),
        )
    if "uq_company_legacy_source_row" not in indexes:
        op.create_index(
            "uq_company_legacy_source_row",
            "companies",
            ["studio_id", "legacy_source_file", "legacy_source_row"],
            unique=True,
            postgresql_where=sa.text("legacy_source_file IS NOT NULL AND legacy_source_row IS NOT NULL"),
        )


def downgrade() -> None:
    raise RuntimeError(
        "No se permite revertir automáticamente la migración histórica: "
        "podría eliminar identificadores y datos de origen ya importados."
    )
