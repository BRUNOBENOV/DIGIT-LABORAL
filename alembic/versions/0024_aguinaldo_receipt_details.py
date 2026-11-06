"""Aguinaldo receipt payment metadata, separate from immutable annual calculations.

Revision ID: 0024_aguinaldo_receipt
Revises: 0023_salary_receipt
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_aguinaldo_receipt"
down_revision = "0023_salary_receipt"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("aguinaldo_receipt_details"):
        op.create_table(
            "aguinaldo_receipt_details",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("employee_id", sa.Integer, sa.ForeignKey("employees.id"), nullable=False),
            sa.Column("source_kind", sa.String(20), nullable=False),
            sa.Column("source_id", sa.Integer, nullable=False),
            sa.Column("payment_method", sa.String(80), nullable=False, server_default=""),
            sa.Column("payment_date", sa.Date, nullable=True),
            sa.Column("updated_by", sa.String(180), nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("source_kind", "source_id", name="uq_aguinaldo_receipt_source"),
        )
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("aguinaldo_receipt_details")}
    if "ix_aguinaldo_receipt_details_company_id" not in indexes:
        op.create_index("ix_aguinaldo_receipt_details_company_id", "aguinaldo_receipt_details", ["company_id"])
    if "ix_aguinaldo_receipt_details_employee_id" not in indexes:
        op.create_index("ix_aguinaldo_receipt_details_employee_id", "aguinaldo_receipt_details", ["employee_id"])
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE aguinaldo_receipt_details ENABLE ROW LEVEL SECURITY")
        op.execute("DROP POLICY IF EXISTS aguinaldo_receipt_studio_access ON aguinaldo_receipt_details")
        op.execute("""
          CREATE POLICY aguinaldo_receipt_studio_access ON aguinaldo_receipt_details
          USING (
            current_setting('app.is_superadmin', true) = 'true'
            OR EXISTS (
              SELECT 1 FROM companies
              WHERE companies.id = aguinaldo_receipt_details.company_id
                AND companies.studio_id = NULLIF(current_setting('app.current_studio_id', true), '')::integer
            )
          )
          WITH CHECK (
            current_setting('app.is_superadmin', true) = 'true'
            OR EXISTS (
              SELECT 1 FROM companies
              WHERE companies.id = aguinaldo_receipt_details.company_id
                AND companies.studio_id = NULLIF(current_setting('app.current_studio_id', true), '')::integer
            )
          )
        """)


def downgrade():
    # Receipt payment evidence and audit history must be retained.
    pass
