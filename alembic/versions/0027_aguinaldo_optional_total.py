"""Allow an aguinaldo amount to be recorded without a remuneration total."""

import sqlalchemy as sa
from alembic import op

revision = "0027_aguinaldo_optional_total"
down_revision = "0026_mov_export_detail"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("aguinaldos") as batch:
        batch.alter_column("total_remunerations", existing_type=sa.Integer(), nullable=True)


def downgrade():
    missing_totals = op.get_bind().execute(sa.text(
        "SELECT 1 FROM aguinaldos WHERE total_remunerations IS NULL LIMIT 1"
    )).first()
    if missing_totals:
        raise RuntimeError("Hay aguinaldos sin total de remuneraciones. El esquema anterior no admite esos registros.")
    with op.batch_alter_table("aguinaldos") as batch:
        batch.alter_column("total_remunerations", existing_type=sa.Integer(), nullable=False)
