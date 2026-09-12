from datetime import UTC, datetime, timedelta
from itertools import count

import pytest

from find_hub_tracker.models import (
    BatteryAlert,
    DeviceInfo,
    DeviceLocation,
    ServiceHeartBeat,
)

# Fixed reference time so ordering/range tests are deterministic and don't
# depend on wall-clock timing. Use this (with timedelta offsets) instead of
# datetime.now()/utc_now() wherever a test needs "row A is before row B".
BASE_TIME = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def make_device():
    """Factory for an unsaved DeviceInfo with sensible defaults.

    Does NOT add/commit to a session — callers decide when to persist,
    so tests can build up related rows (locations, alerts) referencing
    the same device_id before committing anything.

    The id counter lives inside this fixture (not at module scope) so it
    resets to 1 for every test, instead of climbing across the whole
    test session and leaking state between unrelated tests.
    """
    device_ids = count(1)

    def _make(**overrides):
        n = next(device_ids)
        defaults = {
            "id": f"device-{n}",
            "name": f"Device {n}",
            "device_type": "phone",
            "model": "TestModel",
            "first_seen": BASE_TIME,
            "last_seen": BASE_TIME,
        }
        defaults.update(overrides)
        return DeviceInfo(**defaults)

    return _make


@pytest.fixture()
def make_location():
    """Factory for an unsaved DeviceLocation. Always pass device_id
    explicitly to associate it with a device. No id counter needed here:
    DeviceLocation.id is an auto-increment primary key SQLite assigns on
    insert."""

    def _make(*, device_id, **overrides):
        defaults = {
            "device_id": device_id,
            "latitude": 40.7128,
            "longitude": -74.0060,
            "accuracy_meters": 10.0,
            "battery_percent": 80,
            "is_charging": False,
            "timestamp": BASE_TIME,
            "polled_at": BASE_TIME,
        }
        defaults.update(overrides)
        return DeviceLocation(**defaults)

    return _make


@pytest.fixture()
def make_alert():
    """Factory for an unsaved BatteryAlert. Always pass device_id
    explicitly to associate it with a device. No id counter needed here
    either, for the same reason as make_location above."""

    def _make(*, device_id, **overrides):
        defaults = {
            "device_id": device_id,
            "battery_percent": 15,
            "is_critical": False,
            "alert_time": BASE_TIME,
        }
        defaults.update(overrides)
        return BatteryAlert(**defaults)

    return _make


@pytest.fixture()
def make_heartbeat():
    """Factory for an unsaved ServiceHeartBeat."""

    def _make(**overrides):
        defaults = {
            "service_name": "poller",
            "host": "host-1",
            "last_heartbeat": BASE_TIME,
            "poll_count": 0,
            "error_count": 0,
            "started_at": BASE_TIME,
            "version": "1.0.0",
        }
        defaults.update(overrides)
        return ServiceHeartBeat(**defaults)

    return _make


@pytest.fixture()
def base_time():
    """Convenience fixture form of BASE_TIME for tests that prefer
    fixture injection over importing the constant directly."""
    return BASE_TIME


@pytest.fixture()
def hours_ago():
    """Helper to build timestamps relative to BASE_TIME, e.g.
    hours_ago(2) -> BASE_TIME - 2 hours. Use for readable ordering tests."""

    def _hours_ago(n):
        return BASE_TIME - timedelta(hours=n)

    return _hours_ago


@pytest.fixture()
def days_ago():
    """Helper to build timestamps relative to BASE_TIME, e.g.
    days_ago(2) -> BASE_TIME - 2 days. Use for readable ordering tests."""

    def _days_ago(n):
        return BASE_TIME - timedelta(days=n)

    return _days_ago


@pytest.fixture()
def minutes_ago():
    """Helper to build timestamps relative to BASE_TIME, e.g.
    minutes_ago(2) -> BASE_TIME - 2 minutes. Use for readable ordering tests."""

    def _minutes_ago(n):
        return BASE_TIME - timedelta(minutes=n)

    return _minutes_ago
