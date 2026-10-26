from types import SimpleNamespace

from app import tenant_security


def test_rls_tenant_functions_pin_search_path(monkeypatch) -> None:
    executed: list[str] = []

    class FakeConnection:
        def execute(self, statement) -> None:
            executed.append(str(statement))

    class FakeTransaction:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, exc_type, exc_value, traceback) -> bool:
            return False

    class FakeEngine:
        dialect = SimpleNamespace(name="postgresql")

        def begin(self):
            return FakeTransaction()

    monkeypatch.setattr(
        tenant_security,
        "inspect",
        lambda _engine: SimpleNamespace(get_table_names=lambda: []),
    )

    tenant_security.apply_postgres_rls(FakeEngine())

    sql = "\n".join(executed)
    assert "CREATE OR REPLACE FUNCTION public.digit_current_studio_id()" in sql
    assert "CREATE OR REPLACE FUNCTION public.digit_is_superadmin()" in sql
    assert sql.count("SET search_path = pg_catalog, pg_temp") == 2
    assert sql.count("AS $digit$") == 2
    assert sql.count("\\n            $digit$") == 2
