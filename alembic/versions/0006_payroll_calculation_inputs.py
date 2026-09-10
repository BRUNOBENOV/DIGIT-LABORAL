"""Conservar las bases de cada nómina sin recalcular su historia."""
from alembic import op
import sqlalchemy as sa

revision = "0006_payroll_calculation_inputs"
down_revision = "0005_v20_security_event_ip_index"
branch_labels = None
depends_on = None

def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("payroll_lines")}
    for column in (
        sa.Column("ips_base", sa.Integer(), nullable=True),
        sa.Column("ips_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("ips_basis_note", sa.String(300), nullable=False, server_default=""),
        sa.Column("other_discount_note", sa.String(300), nullable=False, server_default=""),
    ):
        if column.name not in columns:
            op.add_column("payroll_lines", column)

def downgrade():
    for name in ("other_discount_note", "ips_basis_note", "ips_rate", "ips_base"):
        op.drop_column("payroll_lines", name)
