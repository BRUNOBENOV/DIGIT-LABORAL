"""Index security events by IP for database-backed rate limits.

Revision ID: 0005_v20_security_event_ip_index
Revises: 0004_v20_compliance_idempotency
"""
from __future__ import annotations
from alembic import op

revision = "0005_v20_security_event_ip_index"
down_revision = "0004_v20_compliance_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_security_events_ip_address", "security_events", ["ip_address"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_security_events_ip_address", table_name="security_events")
