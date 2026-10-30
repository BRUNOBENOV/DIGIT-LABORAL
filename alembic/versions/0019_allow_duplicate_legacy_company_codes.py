"""Allow duplicate source company codes in historical imports.

Revision ID: 0019_allow_duplicate_legacy_company_codes
Revises: 0018_legacy_company_import
"""
from alembic import op
import sqlalchemy as sa

revision = "0019_allow_duplicate_legacy_company_codes"
down_revision = "0018_legacy_company_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("companies")}
    if "uq_company_legacy_code_per_studio" in indexes:
        op.drop_index("uq_company_legacy_code_per_studio", table_name="companies")


def downgrade() -> None:
    raise RuntimeError(
        "No se puede restaurar la unicidad del código histórico: "
        "la migración puede contener varios registros del mismo código de origen."
    )
