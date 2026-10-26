"""Index uncovered foreign-key columns for common joins.

Revision ID: 0012_fk_lookup_indexes
Revises: 0011_int_batch_blobs
"""
from alembic import op
import sqlalchemy as sa


revision = "0012_fk_lookup_indexes"
down_revision = "0011_int_batch_blobs"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _tables()
    if "employees" in tables and "ix_employees_branch_id" not in _indexes("employees"):
        op.create_index("ix_employees_branch_id", "employees", ["branch_id"], unique=False)
    if (
        "request_workflows" in tables
        and "ix_request_workflows_approved_by_user_id" not in _indexes("request_workflows")
    ):
        op.create_index(
            "ix_request_workflows_approved_by_user_id",
            "request_workflows",
            ["approved_by_user_id"],
            unique=False,
        )


def downgrade() -> None:
    # Retain these indexes during downgrade because they may have been created by
    # an out-of-band production hardening migration before this revision is deployed.
    pass
