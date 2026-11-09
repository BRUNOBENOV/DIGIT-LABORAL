"""Separate, auditable reconciliation of historical MOV salary evidence.

Revision ID: 0025_historical_mov
Revises: 0024_aguinaldo_receipt
"""
from alembic import op
import sqlalchemy as sa

revision = "0025_historical_mov"
down_revision = "0024_aguinaldo_receipt"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("historical_mov_reconciliations"):
        return
    op.create_table(
        "historical_mov_reconciliations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("studio_id", sa.Integer(), sa.ForeignKey("studios.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("employee_events.id"), nullable=False),
        sa.Column("calculation_record_id", sa.Integer(), sa.ForeignKey("calculation_records.id"), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("reviewed_by", sa.String(180), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_mov_reconciliation_event"),
        sa.UniqueConstraint("calculation_record_id", name="uq_mov_reconciliation_calculation"),
    )
    for field in ("studio_id", "company_id", "employee_id", "event_id", "calculation_record_id"):
        op.create_index(f"ix_historical_mov_reconciliations_{field}", "historical_mov_reconciliations", [field])


def downgrade():
    op.drop_table("historical_mov_reconciliations")
