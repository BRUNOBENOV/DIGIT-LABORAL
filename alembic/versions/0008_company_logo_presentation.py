"""Persist per-company logo presentation settings."""

from alembic import op
import sqlalchemy as sa

revision = "0008_company_logo_presentation"
down_revision = "0007_request_notifications"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    columns = _columns("company_branding")
    additions = [
        sa.Column("logo_fit", sa.String(12), nullable=False, server_default="contain"),
        sa.Column("logo_scale", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("logo_alignment", sa.String(12), nullable=False, server_default="center"),
        sa.Column("logo_background", sa.String(16), nullable=False, server_default="white"),
    ]
    for column in additions:
        if column.name not in columns:
            op.add_column("company_branding", column)


def downgrade() -> None:
    columns = _columns("company_branding")
    for name in ("logo_background", "logo_alignment", "logo_scale", "logo_fit"):
        if name in columns:
            op.drop_column("company_branding", name)
