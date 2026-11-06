"""Real PostgreSQL startup/upgrade and RLS, only in an explicitly disposable DB."""
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError


def test_postgres_notice_migration_fresh_upgrade_and_read_only_rls():
    raw = os.environ.get("NOTICE_RULES_TEST_DATABASE_URL", "")
    if not raw:
        pytest.skip("Disposable PostgreSQL is provided by CI")
    url = make_url(raw)
    assert url.host in {"localhost", "127.0.0.1"} and url.database == "notice_migrations", "Refusing a non-test database"
    engine = create_engine(url)
    with engine.connect() as connection:
        # Never clean/reuse an existing database supplied accidentally.
        assert connection.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")) == 0
    env = dict(os.environ, DATABASE_URL=raw, MIGRATION_DATABASE_URL=raw, ENVIRONMENT="development")

    def startup():
        result = subprocess.run([sys.executable, "-c", "from app.migration_service import run_migrations; run_migrations()"],
                                env=env, capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]

    def verify():
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0024_aguinaldo_receipt"
            assert connection.scalar(text("SELECT count(*) FROM notice_rule_sets")) == 1
            assert list(connection.execute(text("SELECT max_service_months,notice_days FROM notice_rule_bands ORDER BY position"))) == [(12,30),(60,45),(120,60),(None,90)]
            assert connection.scalar(text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname IN ('notice_rule_sets','notice_rule_bands') AND c.relrowsecurity")) == 2
            assert connection.scalar(text("SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename IN ('notice_rule_sets','notice_rule_bands') AND cmd='SELECT'")) == 2
    startup()  # Fresh metadata + stamp must also install seeds and policies.
    verify()
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE notice_rule_bands"))
        connection.execute(text("DROP TABLE notice_rule_sets"))
        connection.execute(text("UPDATE alembic_version SET version_num='0020_salary_import_details'"))
    startup()  # Existing installation: reconcile + real Alembic upgrade.
    verify()
    startup()  # Repeated startup is idempotent.
    verify()
    with engine.begin() as connection:
        connection.execute(text("CREATE ROLE notice_reader_test NOLOGIN"))
        connection.execute(text("GRANT USAGE ON SCHEMA public TO notice_reader_test"))
        # Even a mistakenly granted DML privilege must not bypass RLS.
        connection.execute(text("GRANT SELECT,INSERT,UPDATE,DELETE ON notice_rule_sets,notice_rule_bands TO notice_reader_test"))
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE notice_reader_test"))
        assert connection.scalar(text("SELECT count(*) FROM notice_rule_bands")) == 4
        assert connection.execute(text("UPDATE notice_rule_bands SET notice_days=1")).rowcount == 0
        assert connection.execute(text("DELETE FROM notice_rule_bands")).rowcount == 0
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE notice_reader_test"))
            connection.execute(text("INSERT INTO notice_rule_bands (id,rule_set_id,position,max_service_months,notice_days) VALUES (9000,1,99,999,1)"))
    verify()
    engine.dispose()
