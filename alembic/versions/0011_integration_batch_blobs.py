"""Keep generated integration batches and submission proofs durable.

Revision ID: 0011_integration_batch_blobs
Revises: 0010_req_attach_bytes
"""
from alembic import op
import sqlalchemy as sa


revision = "0011_int_batch_blobs"
down_revision = "0010_req_attach_bytes"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "integration_batches" in _tables():
        existing = _columns("integration_batches")
        additions = [
            sa.Column("file_bytes", sa.LargeBinary(), nullable=True),
            sa.Column("receipt_storage_key", sa.String(300), nullable=False, server_default=""),
            sa.Column("receipt_bytes", sa.LargeBinary(), nullable=True),
            sa.Column("receipt_content_type", sa.String(100), nullable=False, server_default="application/octet-stream"),
            sa.Column("receipt_file_name", sa.String(260), nullable=False, server_default=""),
        ]
        for column in additions:
            if column.name not in existing:
                op.add_column("integration_batches", column)


def downgrade() -> None:
    # Retain binary content during downgrade rather than deleting uploaded files.
    pass
