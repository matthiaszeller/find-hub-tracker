from contextlib import contextmanager

import structlog
from sqlalchemy import Engine
from sqlmodel import Session
from sqlmodel import create_engine as _create_engine

from find_hub_tracker.config import Settings
from find_hub_tracker.models import SQLModel

log = structlog.get_logger()


def get_engine(settings: Settings) -> Engine:
    return _create_engine(settings.database_url)


@contextmanager
def get_session(
    engine: Engine, *, commit: bool = False, expire_on_commit: bool = False
):
    with Session(engine, expire_on_commit=expire_on_commit) as session:
        try:
            yield session

            if commit:
                session.commit()
        except Exception:
            # not absolutely needed but make it explicit
            session.rollback()
            raise


def run_migrations(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    log.info("sqlite_migrated")
