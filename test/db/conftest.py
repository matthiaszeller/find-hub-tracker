from contextlib import contextmanager

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlmodel import Session

from find_hub_tracker.db.core import run_migrations


@pytest.fixture
def fresh_engine():
    """
    Fresh engine in memory.

    StaticPool keeps the single in-memory connection alive for the
    lifetime of the engine (default pooling would give every checkout a
    brand-new, empty in-memory DB).
    """
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture()
def engine(fresh_engine):
    """In-memory SQLite engine with a fresh schema per test."""
    run_migrations(fresh_engine)
    return fresh_engine


@pytest.fixture
def session_maker(engine):
    @contextmanager
    def _make():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    return _make


@pytest.fixture()
def session(session_maker):
    """A session per test, matching the expire_on_commit=False default
    used by find_hub_tracker.core.get_session."""
    with session_maker() as session:
        yield session
