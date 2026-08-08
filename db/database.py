"""
db/database.py
==============
Database engine, session factory, and initialisation helpers.

Usage
-----
    from db.database import get_session, init_db

    init_db()           # creates tables on first run (idempotent)

    with get_session() as session:
        accounts = session.query(Account).all()
"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from config import DATABASE_URL
from db.models import Base

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # needed for SQLite + threads
    echo=False,
)


# Enable WAL mode for better concurrent read performance with SQLite.
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Provide a transactional database session.

    Commits on clean exit, rolls back on exception, always closes.

    Example::

        with get_session() as db:
            db.add(some_object)
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Create all database tables if they do not yet exist.

    Safe to call multiple times (idempotent via ``checkfirst=True``).
    """
    Base.metadata.create_all(bind=engine, checkfirst=True)
