from __future__ import annotations

from types import SimpleNamespace

from app import main, tenant_security


def test_current_user_sets_signed_identity_before_rls_protected_lookup(monkeypatch) -> None:
    snapshots: list[dict[str, object]] = []
    user = SimpleNamespace(id=42, studio_id=7, role="administrador")

    class FakeSession:
        def __init__(self) -> None:
            self.info: dict[str, object] = {}
            self.context_at_user_lookup: dict[str, object] | None = None

        def get(self, model, user_id):  # noqa: ANN001
            assert model is main.User
            self.context_at_user_lookup = dict(self.info)
            return user if user_id == user.id else None

    db = FakeSession()

    def apply_context(session) -> None:  # noqa: ANN001
        snapshots.append(dict(session.info))

    monkeypatch.setattr(main, "apply_session_tenant_context", apply_context)
    monkeypatch.setattr(
        main,
        "get_or_create_security",
        lambda _db, _user: SimpleNamespace(session_version=8),
    )
    request = SimpleNamespace(
        session={"user_id": "42", "security_version": 8},
    )

    result = main.current_user(request, db)  # type: ignore[arg-type]

    assert result is user
    assert db.context_at_user_lookup is not None
    assert db.context_at_user_lookup["user_id"] == 42
    assert db.context_at_user_lookup["studio_id"] is None
    assert db.context_at_user_lookup["user_role"] == ""
    assert db.context_at_user_lookup["is_superadmin"] is False
    assert snapshots[-1]["user_id"] == 42
    assert snapshots[-1]["studio_id"] == 7
    assert snapshots[-1]["user_role"] == "administrador"
    assert snapshots[-1]["is_superadmin"] is False


def test_invalid_session_user_id_is_cleared_without_database_lookup(monkeypatch) -> None:
    class FakeSession:
        info: dict[str, object] = {}

        def get(self, *_args):  # noqa: ANN002
            raise AssertionError("An invalid signed user ID must not reach the database.")

    request = SimpleNamespace(session={"user_id": "not-an-integer", "security_version": 1})
    monkeypatch.setattr(
        main,
        "apply_session_tenant_context",
        lambda _db: (_ for _ in ()).throw(AssertionError("Invalid ID must be rejected first.")),
    )

    assert main.current_user(request, FakeSession()) is None  # type: ignore[arg-type]
    assert request.session == {}


def test_rls_policies_cover_sensitive_identity_tables(monkeypatch) -> None:
    statements: list[str] = []
    table_names = {
        "studios",
        "users",
        "user_security",
        "password_reset_tokens",
        "activation_requests",
        "companies",
        "employees",
        "company_sections",
    }

    class FakeConnection:
        def execute(self, statement) -> None:  # noqa: ANN001
            statements.append(str(statement))

        def exec_driver_sql(self, statement: str) -> None:
            statements.append(statement)

    class FakeTransaction:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, exc_type, exc_value, traceback) -> bool:  # noqa: ANN001
            return False

    class FakeEngine:
        dialect = SimpleNamespace(name="postgresql")

        def begin(self):
            return FakeTransaction()

    monkeypatch.setattr(
        tenant_security,
        "inspect",
        lambda _engine: SimpleNamespace(get_table_names=lambda: table_names),
    )

    tenant_security.apply_postgres_rls(FakeEngine())  # type: ignore[arg-type]
    sql = "\n".join(statements)

    assert "CREATE OR REPLACE FUNCTION public.digit_current_user_id()" in sql
    for table in table_names:
        assert f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY' in sql
        assert f'CREATE POLICY "digit_tenant_{table}" ON "{table}"' in sql

    assert "id = digit_current_user_id()" in sql
    assert "current_setting('app.current_user_role', true) = 'administrador'" in sql
    assert "user_id = digit_current_user_id()" in sql
    assert 'digit_is_superadmin() OR (FALSE)' in sql
    assert 'CREATE POLICY "digit_tenant_company_sections" ON "company_sections"' in sql
    assert "company_id IN (SELECT id FROM companies WHERE studio_id = digit_current_studio_id())" in sql

def test_runtime_rls_check_warns_when_application_role_owns_tables(monkeypatch) -> None:
    from app import database

    class FakeResult:
        def mappings(self):
            return self

        def one(self):
            return {"role_name": "digit_app", "can_bypass_rls": False, "owned_tables": 39}

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> bool:  # noqa: ANN001
            return False

        def execute(self, _statement):  # noqa: ANN001
            return FakeResult()

    class FakeEngine:
        dialect = SimpleNamespace(name="postgresql")

        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(database, "engine", FakeEngine())
    monkeypatch.setattr(database, "settings", SimpleNamespace(rls_enabled=True))

    warnings = database.postgres_rls_role_issues()

    assert any("propietario de tablas" in warning for warning in warnings)
    assert not any("BYPASSRLS" in warning for warning in warnings)
