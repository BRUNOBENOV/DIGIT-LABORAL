"""Optional documented MOV export supplements, without changing original payroll.

Revision ID: 0026_mov_export_detail
Revises: 0025_historical_mov
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_mov_export_detail"
down_revision = "0025_historical_mov"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("historical_mov_export_details"):
        return
    op.create_table(
        "historical_mov_export_details",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("studio_id", sa.Integer(), sa.ForeignKey("studios.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("employee_events.id"), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("days_worked", sa.Integer(), nullable=True),
        sa.Column("days_paid", sa.Integer(), nullable=True),
        sa.Column("hours_worked", sa.Numeric(8, 2), nullable=True),
        sa.Column("pay_basis", sa.String(12), nullable=True),
        sa.Column("ips_base", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(180), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_mov_export_detail_event"),
    )
    for column in ("studio_id", "company_id", "employee_id", "event_id"):
        op.create_index(f"ix_historical_mov_export_details_{column}", "historical_mov_export_details", [column])


def downgrade():
    op.drop_table("historical_mov_export_details")
