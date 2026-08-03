from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


def normalize_database_url(url: str) -> str:
    # Algunos proveedores entregan postgres://, mientras SQLAlchemy usa postgresql+psycopg://
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


DATABASE_URL = normalize_database_url(settings.database_url)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def apply_session_tenant_context(session: Session) -> None:
    if engine.dialect.name != "postgresql" or not settings.rls_enabled:
        return
    studio_id = session.info.get("studio_id")
    is_superadmin = bool(session.info.get("is_superadmin"))
    session.execute(text("SELECT set_config('app.is_superadmin', :value, true)"), {"value": "true" if is_superadmin else "false"})
    session.execute(text("SELECT set_config('app.current_studio_id', :value, true)"), {"value": str(studio_id or "")})


@event.listens_for(Session, "after_begin")
def _set_tenant_context_after_begin(session: Session, transaction, connection) -> None:  # noqa: ANN001
    if connection.dialect.name != "postgresql" or not settings.rls_enabled:
        return
    studio_id = session.info.get("studio_id")
    is_superadmin = bool(session.info.get("is_superadmin"))
    connection.execute(text("SELECT set_config('app.is_superadmin', :value, true)"), {"value": "true" if is_superadmin else "false"})
    connection.execute(text("SELECT set_config('app.current_studio_id', :value, true)"), {"value": str(studio_id or "")})
