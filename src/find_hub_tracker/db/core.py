from contextlib import contextmanager

from sqlalchemy import Engine
from sqlmodel import Session, create_engine as _create_engine

from find_hub_tracker.config import Settings


def get_engine(settings: Settings) -> Engine:
    return _create_engine(settings.database_url)


@contextmanager
def get_session(engine: Engine, *, commit: bool = False):
    with Session(engine) as session:
        yield session

        if commit:
            session.commit()
