"""Versioned notice periods and calendar reference

Revision ID: 0021_notice_rules
Revises: 0020_salary_import_details
Create Date: 2026-11-02 15:59:39.537726
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0021_notice_rules'
down_revision: Union[str, None] = '0020_salary_import_details'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    from app.notice_rule_schema import install_notice_rules
    install_notice_rules(op.get_bind())

def downgrade() -> None:
    op.drop_table("notice_rule_bands")
    op.drop_table("notice_rule_sets")
