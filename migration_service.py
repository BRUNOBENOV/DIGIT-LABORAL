from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from .config import settings
from .database import Base, engine, normalize_database_url
from . import models as _models  # noqa: F401

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent

_raw_migration_url = (settings.migration_database_url or settings.database_url).strip()
MIGRATION_DATABASE_URL = normalize_database_url(_raw_migration_url)

_engine_url = engine.url.render_as_string(hide_password=False)
migration_engine = (
    engine
    if _engine_url == MIGRATION_DATABASE_URL
    else create_engine(MIGRATION_DATABASE_URL, pool_pre_ping=True)
)


def _alembic_config() -> Config:
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    real_url = migration_engine.url.render_as_string(hide_password=False)
    cfg.set_main_option("sqlalchemy.url", real_url.replace("%", "%%"))
    return cfg


def _reconcile_v20_schema() -> None:
    Base.metadata.create_all(migration_engine)

    if migration_engine.dialect.name != "postgresql":
        return

    with migration_engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE IF EXISTS compliance_events "
            "ADD COLUMN IF NOT EXISTS branch_id INTEGER NULL"
        ))
        connection.execute(text(
            "ALTER TABLE IF EXISTS compliance_events "
            "ADD COLUMN IF NOT EXISTS source_key VARCHAR(180) NULL"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_compliance_events_branch_id "
            "ON compliance_events (branch_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_compliance_events_source_key "
            "ON compliance_events (source_key)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_security_events_ip_address "
            "ON security_events (ip_address)"
        ))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_compliance_event_source_idx "
            "ON compliance_events (company_id, authority, source_key) "
            "WHERE source_key IS NOT NULL"
        ))


def run_migrations() -> None:
    cfg = _alembic_config()
    inspector = inspect(migration_engine)
    tables = set(inspector.get_table_names())

    if not tables:
        _reconcile_v20_schema()
        command.stamp(cfg, "head")
        logger.info("Fresh database created and stamped at Alembic head")
        return

    _reconcile_v20_schema()
    command.stamp(cfg, "head", purge=True)
    logger.info("Database reconciled with Digit Laboral v20 and stamped at Alembic head")
