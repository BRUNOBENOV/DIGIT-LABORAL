"""Persistir datos complementarios a liquidaciones sin modificar cálculos.

Revision ID: 0020_salary_import_details
Revises: 0019_employee_exit_settlement
"""
from alembic import op
import sqlalchemy as sa

revision = "0020_salary_import_details"
down_revision = "0019_employee_exit_settlement"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("salary_import_details"):
        op.create_table(
            "salary_import_details",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("calculation_record_id", sa.Integer(), sa.ForeignKey("calculation_records.id"), nullable=False),
            sa.Column("source_sha256", sa.String(64), nullable=False, server_default=""),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("days_worked", sa.Integer(), nullable=False),
            sa.Column("hours_worked", sa.Numeric(10, 2), nullable=False),
            sa.Column("payment_method", sa.String(100), nullable=False, server_default=""),
            sa.Column("updated_by", sa.String(180), nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("calculation_record_id", name="uq_salary_import_detail_calculation"),
        )
    existing = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("salary_import_details")}
    if "ix_salary_import_details_company_id" not in existing:
        op.create_index("ix_salary_import_details_company_id", "salary_import_details", ["company_id"])
    if "ix_salary_import_details_calculation_record_id" not in existing:
        op.create_index("ix_salary_import_details_calculation_record_id", "salary_import_details", ["calculation_record_id"])


def downgrade():
    op.drop_table("salary_import_details")
