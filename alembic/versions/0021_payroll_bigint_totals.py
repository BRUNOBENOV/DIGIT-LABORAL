"""Ampliar totales de nómina para evitar desbordamientos por miles de legajos.

Revision ID: 0021_payroll_bigint_totals
Revises: 0020_salary_import_details

No toca ni recalcula datos de trabajadores; solo amplía columnas agregadas.
"""
from alembic import op
import sqlalchemy as sa

revision = "0021_payroll_bigint_totals"
down_revision = "0020_salary_import_details"
branch_labels = None
depends_on = None

TOTALS = ("total_gross", "total_ips_employee", "total_discounts", "total_net")


def _change(to_type, check_type):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {column["name"]: column for column in inspector.get_columns("payrolls")}
    for name in TOTALS:
        if name not in columns:
            raise RuntimeError(f"Columna requerida ausente: payrolls.{name}")
    needed = [
        name for name in TOTALS
        if not isinstance(columns[name]["type"], check_type)
    ]
    if not needed:
        return
    # PostgreSQL can alter these columns in place. batch_alter_table
    # additionally supports migration testing on SQLite.
    with op.batch_alter_table("payrolls") as batch:
        for name in needed:
            batch.alter_column(
                name,
                existing_type=columns[name]["type"],
                type_=to_type,
                existing_nullable=columns[name]["nullable"],
            )


def upgrade():
    _change(sa.BigInteger(), sa.BigInteger)


def downgrade():
    # Downgrading could truncate a legitimate payroll total. Refuse until
    # a deliberate migration verifies all values fit into signed INT32.
    raise RuntimeError(
        "No es seguro reducir BIGINT a INTEGER sin comprobar los importes: "
        "los totales podrían superar 2.147.483.647."
    )
