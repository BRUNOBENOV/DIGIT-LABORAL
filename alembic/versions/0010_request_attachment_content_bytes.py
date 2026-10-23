"""Store a durable database fallback for uploaded request attachments.

Revision ID: 0010_req_attach_bytes
Revises: 0009_official_certificates
"""
from alembic import op
import sqlalchemy as sa


revision = "0010_req_attach_bytes"
down_revision = "0009_official_certificates"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "request_attachments" in _tables() and "content_bytes" not in _columns("request_attachments"):
        op.add_column("request_attachments", sa.Column("content_bytes", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    # Intentionally retain this nullable data column on downgrade. Dropping it
    # would permanently delete uploaded request attachment bytes.
    pass
