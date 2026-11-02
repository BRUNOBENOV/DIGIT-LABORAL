"""Pruebas de migración de totales monetarios grandes."""
from __future__ import annotations
import importlib.util
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_migration_0021_preserves_history_and_allows_billions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'payroll_0021.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE payrolls (id INTEGER PRIMARY KEY, "
            "total_gross INTEGER NOT NULL, total_ips_employee INTEGER NOT NULL, "
            "total_discounts INTEGER NOT NULL, total_net INTEGER NOT NULL)"
        ))
        conn.execute(text("INSERT INTO payrolls VALUES (1, 1000000, 90000, 90000, 910000)"))
        spec = importlib.util.spec_from_file_location(
            "bigint_migration", "alembic/versions/0021_payroll_bigint_totals.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        columns = {c["name"]: str(c["type"]).upper() for c in inspect(conn).get_columns("payrolls")}
        for name in ("total_gross", "total_ips_employee", "total_discounts", "total_net"):
            assert "BIGINT" in columns[name]
        old = conn.execute(text("SELECT total_gross, total_net FROM payrolls WHERE id=1")).one()
        assert tuple(old) == (1000000, 910000)
        conn.execute(text(
            "INSERT INTO payrolls VALUES (2, 6000000000, 540000000, 540000000, 5460000000)"
        ))
        current = conn.execute(text("SELECT total_gross, total_net FROM payrolls WHERE id=2")).one()
        assert tuple(current) == (6000000000, 5460000000)
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        assert conn.scalar(text("SELECT COUNT(*) FROM payrolls")) == 2
    engine.dispose()
