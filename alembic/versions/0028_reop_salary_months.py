"""Payment choices and observed REOP communications by company and month."""
from alembic import op
import sqlalchemy as sa

revision = "0028_reop_salary_months"
down_revision = "0027_aguinaldo_optional_total"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("reop_salary_months"):
        op.create_table(
            "reop_salary_months",
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("period", sa.String(7), primary_key=True),
            sa.Column("payments", sa.JSON(), nullable=False),
            sa.Column("snapshots", sa.JSON(), nullable=False),
        )


def downgrade():
    op.drop_table("reop_salary_months")
