"""Add payment evidence fields to non-destructive salary receipt supplements.

Revision ID: 0023_salary_receipt
Revises: 0022_vacation_payment
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_salary_receipt"
down_revision = "0022_vacation_payment"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {col["name"] for col in inspector.get_columns("salary_import_details")}
    if "payment_date" not in columns:
        op.add_column("salary_import_details", sa.Column("payment_date", sa.Date(), nullable=True))
    if "pieces_or_tasks" not in columns:
        op.add_column("salary_import_details", sa.Column("pieces_or_tasks", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("salary_import_details", "pieces_or_tasks")
    op.drop_column("salary_import_details", "payment_date")
