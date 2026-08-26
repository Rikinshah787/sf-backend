from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _engine_kwargs(database_url: str) -> dict:
    if not database_url.startswith("sqlite"):
        return {}

    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if ":memory:" in database_url or "mode=memory" in database_url:
        # A plain in-memory SQLite database lives and dies with its connection.
        # StaticPool keeps a single connection alive so every request — and every
        # thread FastAPI hands work to — sees the same data for the process's lifetime.
        kwargs["poolclass"] = StaticPool
    return kwargs


settings = get_settings()

engine = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    **_engine_kwargs(settings.database_url),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _migrate_legacy_addresses() -> None:
    """
    One-shot, idempotent upgrade for persistent databases created before the
    addresses table existed: copy each contact's flat postal columns into a
    single 'home' Address row, then drop the legacy columns.
    """
    columns = {column["name"] for column in inspect(engine).get_columns("contacts")}
    legacy = ("address", "city", "state", "postal_code", "country")
    if not set(legacy) <= columns:
        return  # already migrated (or a fresh database)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO addresses"
                " (contact_id, type, address, city, state, postal_code, country)"
                " SELECT id, 'home', address, city, state, postal_code, country"
                " FROM contacts"
                " WHERE COALESCE(address, city, state, postal_code, country) IS NOT NULL"
                "   AND id NOT IN (SELECT contact_id FROM addresses)"
            )
        )
        for column in legacy:
            conn.execute(text(f"ALTER TABLE contacts DROP COLUMN {column}"))


def init_db() -> None:
    """Create tables. Called on startup; safe to call repeatedly."""
    from app import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)
    _migrate_legacy_addresses()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
