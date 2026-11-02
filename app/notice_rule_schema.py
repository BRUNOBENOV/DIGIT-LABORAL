"""Idempotent installation used by Alembic and fresh database initialization."""
from datetime import UTC, date, datetime

from sqlalchemy import select, text

from .models import NoticeRuleBand, NoticeRuleSet
from .notice_scale import published_rule


def install_notice_rules(connection) -> None:
    NoticeRuleSet.__table__.create(connection, checkfirst=True)
    NoticeRuleBand.__table__.create(connection, checkfirst=True)
    rule = published_rule()
    rule_id = connection.scalar(select(NoticeRuleSet.id).where(NoticeRuleSet.code == rule["code"]))
    if rule_id is None:
        rule_id = connection.execute(NoticeRuleSet.__table__.insert().values(
            code=rule["code"], jurisdiction=rule["jurisdiction"],
            effective_from=date.fromisoformat(rule["effective_from"]), active=True,
            legal_basis=rule["legal_basis"], source_url=rule["source_url"],
            source_notes=rule["source_notes"], created_at=datetime.now(UTC),
        )).inserted_primary_key[0]
        connection.execute(NoticeRuleBand.__table__.insert(), [
            dict(rule_set_id=rule_id, **band) for band in rule["bands"]
        ])
    # Global legal configuration has no personal information. Only the backend
    # owner/migration role can write; browser API roles cannot access these tables.
    if connection.dialect.name == "postgresql":
        for table in ("notice_rule_sets", "notice_rule_bands"):
            connection.execute(text(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY"))
            connection.execute(text(f"DROP POLICY IF EXISTS notice_rules_read ON public.{table}"))
            connection.execute(text(f"CREATE POLICY notice_rules_read ON public.{table} FOR SELECT USING (true)"))
            connection.execute(text(f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC"))
            for role in ("anon", "authenticated"):
                if connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}):
                    connection.execute(text(f"REVOKE ALL ON TABLE public.{table} FROM {role}"))
