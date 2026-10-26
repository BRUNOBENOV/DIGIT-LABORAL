"""Pin search_path for tenant context functions in existing databases.

Revision ID: 0013_tenant_function_search_path
Revises: 0012_fk_lookup_indexes
"""
from alembic import op


revision = "0013_tenant_function_search_path"
down_revision = "0012_fk_lookup_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        DO $migration$
        BEGIN
            IF to_regprocedure('public.digit_current_studio_id()') IS NOT NULL THEN
                ALTER FUNCTION public.digit_current_studio_id()
                    SET search_path = pg_catalog, pg_temp;
            END IF;
            IF to_regprocedure('public.digit_is_superadmin()') IS NOT NULL THEN
                ALTER FUNCTION public.digit_is_superadmin()
                    SET search_path = pg_catalog, pg_temp;
            END IF;
        END
        $migration$;
        """
    )


def downgrade() -> None:
    # Keep the hardened function configuration when rolling application code back.
    pass
