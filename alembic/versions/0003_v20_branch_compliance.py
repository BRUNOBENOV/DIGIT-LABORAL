"""Add compliance profiles per branch and link events to establishments.

Revision ID: 0003_v20_branch_compliance
Revises: 0002_v20_compliance
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_v20_branch_compliance"
down_revision = "0002_v20_compliance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "branch_compliance_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("ips_employer_number", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("mtess_employer_number", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("department", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("district", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("locality", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("economic_activity", sa.String(length=220), nullable=False, server_default=""),
        sa.Column("activity_code", sa.String(length=60), nullable=False, server_default=""),
        sa.Column("establishment_type", sa.String(length=40), nullable=False, server_default="Sucursal"),
        sa.Column("rei_status", sa.String(length=30), nullable=False, server_default="Pendiente"),
        sa.Column("reop_status", sa.String(length=30), nullable=False, server_default="Pendiente"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("branch_id", name="uq_branch_compliance_profile"),
    )
    op.create_index("ix_branch_compliance_profiles_branch_id", "branch_compliance_profiles", ["branch_id"], unique=False)

    with op.batch_alter_table("compliance_events") as batch:
        batch.add_column(sa.Column("branch_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_compliance_events_branch_id_branches",
            "branches",
            ["branch_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_compliance_events_branch_id", ["branch_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("compliance_events") as batch:
        batch.drop_index("ix_compliance_events_branch_id")
        batch.drop_constraint("fk_compliance_events_branch_id_branches", type_="foreignkey")
        batch.drop_column("branch_id")
    op.drop_index("ix_branch_compliance_profiles_branch_id", table_name="branch_compliance_profiles")
    op.drop_table("branch_compliance_profiles")
