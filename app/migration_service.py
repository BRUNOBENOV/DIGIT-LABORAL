from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from .config import settings
from .database import Base, engine, normalize_database_url
from . import models as _models  # noqa: F401  # Register all SQLAlchemy metadata before create_all.

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent
MIGRATION_DATABASE_URL = normalize_database_url(settings.migration_database_url)
migration_engine = (
    engine
    if str(engine.url) == MIGRATION_DATABASE_URL
    else create_engine(MIGRATION_DATABASE_URL, pool_pre_ping=True)
)


def run_migrations() -> None:
    """Transition a v19 database to Alembic without losing existing data."""
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", str(migration_engine.url).replace("%", "%%"))
    inspector = inspect(migration_engine)
    tables = set(inspector.get_table_names())
    if not tables:
        # Fresh installation: current metadata already contains the v20 schema.
        Base.metadata.create_all(migration_engine)
        command.stamp(cfg, "head")
        logger.info("Fresh database created and stamped at Alembic head")
        return
    if "alembic_version" not in tables:
        # Existing v19 install: establish the baseline and apply v20 changes.
        command.stamp(cfg, "0001_v19_baseline")
    command.upgrade(cfg, "head")
