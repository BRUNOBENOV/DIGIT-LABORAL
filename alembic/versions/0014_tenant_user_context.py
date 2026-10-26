"""Add an RLS-safe lookup function for the authenticated user context.

Revision ID: 0014_tenant_user_context
Revises: 0013_tenant_function_search_path
"""
from alembic import op


revision = "0014_tenant_user_context"
down_revision = "0013_tenant_function_search_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.digit_current_user_id() RETURNS BIGINT
        LANGUAGE SQL STABLE
        SET search_path = pg_catalog, pg_temp
        AS $digit$
            SELECT NULLIF(current_setting('app.current_user_id', true), '')::BIGINT
        $digit$
        """
    )


def downgrade() -> None:
    # Keep this function for compatibility with policies created by application
    # startup. Dropping it during rollback could leave those policies invalid.
    pass
