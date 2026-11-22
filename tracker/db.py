"""Engine and session handling. Only DATABASE_URL differs between SQLite (local) and Postgres (Neon)."""

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from tracker import config
from tracker.models import Base


def make_engine(url: str | None = None) -> Engine:
    url = url or config.DATABASE_URL
    # Neon / some hosts hand out postgres:// or postgresql:// URLs; use the psycopg-agnostic default driver name.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    engine = create_engine(url, future=True)
    if engine.dialect.name == "sqlite":
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite ignores foreign keys unless asked
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = make_engine()
        _SessionLocal = sessionmaker(_engine, expire_on_commit=False)
    return _engine


@contextmanager
def session_scope():
    """Commit on success, roll back on error."""
    get_engine()
    assert _SessionLocal is not None
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_tables(engine: Engine | None = None) -> None:
    Base.metadata.create_all(engine or get_engine())
