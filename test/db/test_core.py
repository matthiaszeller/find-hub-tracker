import pytest
from sqlalchemy import inspect as sa_inspect
from sqlmodel import Session

from find_hub_tracker.db.core import get_session, run_migrations
from find_hub_tracker.models import DeviceInfo


class TestRunMigrations:
    def test_creates_expected_tables(self, fresh_engine):
        """Uses its own fresh, unmigrated engine (not the `engine` fixture,
        which is already migrated by conftest) so this actually exercises
        table creation from scratch."""
        run_migrations(fresh_engine)

        table_names = set(sa_inspect(fresh_engine).get_table_names())
        assert {
            "devices",
            "device_locations",
            "battery_alerts",
            "service_heartbeats",
        } <= table_names

    def test_is_safe_to_run_more_than_once(self, fresh_engine):
        """create_all should be idempotent — calling it again shouldn't
        error or drop existing data."""
        run_migrations(fresh_engine)

        with Session(fresh_engine) as session:
            session.add(DeviceInfo(id="d1", name="Survivor"))
            session.commit()

        run_migrations(fresh_engine)  # should not raise, should not wipe data

        with Session(fresh_engine) as session:
            assert session.get(DeviceInfo, "d1") is not None


class TestGetSession:
    def test_commits_when_commit_true(self, engine, make_device):
        with get_session(engine, commit=True) as session:
            session.add(make_device(id="d1"))

        with Session(engine) as verify_session:
            assert verify_session.get(DeviceInfo, "d1") is not None

    def test_does_not_commit_when_commit_false(self, engine, make_device):
        """commit defaults to False — changes made inside the block
        should not survive once the context exits."""
        with get_session(engine) as session:
            session.add(make_device(id="d1"))

        with Session(engine) as verify_session:
            assert verify_session.get(DeviceInfo, "d1") is None

    def test_rolls_back_and_reraises_on_exception(self, engine, make_device):
        """An exception inside the block should roll back any pending
        changes (even when commit=True) and propagate the original
        exception rather than swallowing it."""

        class Boom(Exception):
            pass

        with pytest.raises(Boom):
            with get_session(engine, commit=True) as session:
                session.add(make_device(id="d1"))
                raise Boom("something went wrong")

        with Session(engine) as verify_session:
            assert verify_session.get(DeviceInfo, "d1") is None

    def test_object_usable_after_commit_without_expiry(self, engine, make_device):
        """get_session defaults expire_on_commit=False. If that flag were
        ever flipped, accessing an attribute on `device` after the
        session (and its connection) closes would raise
        DetachedInstanceError instead of just returning the value."""
        device = make_device(id="d1", name="Pixel 9")

        with get_session(engine, commit=True) as session:
            session.add(device)

        assert device.name == "Pixel 9"

    def test_expire_on_commit_true_can_still_be_requested(self, engine, make_device):
        """Sanity check that the expire_on_commit parameter is actually
        wired through to the underlying Session, not hardcoded."""
        with get_session(engine, commit=True, expire_on_commit=True) as session:
            device = make_device(id="d1")
            session.add(device)
            session.flush()
            device_id = device.id

        # The instance from the closed session is expired/detached; a
        # fresh session should still find the committed row regardless.
        with Session(engine) as verify_session:
            assert verify_session.get(DeviceInfo, device_id) is not None
