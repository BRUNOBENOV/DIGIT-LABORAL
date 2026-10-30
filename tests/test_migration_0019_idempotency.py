"""Alembic 0019 must tolerate the legacy create_all() reconciliation step."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from app.database import Base
from app import models  # noqa: F401 - populate Base metadata


def test_employee_exit_migration_can_reconcile_tables_precreated_by_orm(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'precreated.db'}")
    Base.metadata.create_all(engine)
    path = (
        Path(__file__).resolve().parents[1] /
        "alembic" / "versions" / "0019_employee_exit_settlement.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0019_exit", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    before = {
        table: {item["name"] for item in inspect(engine).get_indexes(table)}
        for table in ("employee_exits", "final_settlements")
    }
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            mod.upgrade()
    after = {
        table: {item["name"] for item in inspect(engine).get_indexes(table)}
        for table in ("employee_exits", "final_settlements")
    }
    assert before == after
    assert "ix_employee_exits_employee_id" in after["employee_exits"]
    assert "ix_final_settlements_employee_exit_id" in after["final_settlements"]
    engine.dispose()
