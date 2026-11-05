"""Registrar respaldo de pago vacacional para reconciliación de salarios REOP.

Revision ID: 0022_vacation_payment
Revises: 0021_notice_rules
"""
from alembic import op
import sqlalchemy as sa

revision = "0022_vacation_payment"
down_revision = "0021_notice_rules"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {col["name"] for col in inspector.get_columns("vacations")}
    if "paid_amount" not in columns:
        op.add_column("vacations", sa.Column("paid_amount", sa.Integer(), nullable=True))
    if "payment_date" not in columns:
        op.add_column("vacations", sa.Column("payment_date", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("vacations", "payment_date")
    op.drop_column("vacations", "paid_amount")
