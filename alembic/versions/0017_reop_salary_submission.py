"""Add links from REOP salary submission batches to saved calculations.

Revision ID: 0017_reop_salary_submission
Revises: 0016_employee_maintenance_fields
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_reop_salary_submission"
down_revision = "0016_employee_maintenance_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "integration_batches" not in set(inspector.get_table_names()):
        return
    columns = {item["name"] for item in inspector.get_columns("integration_batches")}
    if "calculation_record_id" not in columns:
        op.add_column(
            "integration_batches",
            sa.Column(
                "calculation_record_id",
                sa.Integer(),
                sa.ForeignKey("calculation_records.id"),
                nullable=True,
            ),
        )
    if "payload_json" not in columns:
        op.add_column(
            "integration_batches",
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        )
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("integration_batches")}
    if "ix_integration_batches_calculation_record_id" not in indexes:
        op.create_index(
            "ix_integration_batches_calculation_record_id",
            "integration_batches",
            ["calculation_record_id"],
        )


def downgrade() -> None:
    # Retain submission snapshots and their calculation links to preserve auditability.
    pass
