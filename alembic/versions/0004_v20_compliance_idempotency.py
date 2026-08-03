"""Add durable idempotency keys to official communications.

Revision ID: 0004_v20_compliance_idempotency
Revises: 0003_v20_branch_compliance
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_v20_compliance_idempotency"
down_revision = "0003_v20_branch_compliance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("compliance_events") as batch:
        batch.add_column(sa.Column("source_key", sa.String(length=180), nullable=True))
        batch.create_index("ix_compliance_events_source_key", ["source_key"], unique=False)
        batch.create_unique_constraint("uq_compliance_event_source", ["company_id", "authority", "source_key"])


def downgrade() -> None:
    with op.batch_alter_table("compliance_events") as batch:
        batch.drop_constraint("uq_compliance_event_source", type_="unique")
        batch.drop_index("ix_compliance_events_source_key")
        batch.drop_column("source_key")
