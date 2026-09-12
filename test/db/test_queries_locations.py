import pytest
from sqlmodel import select

import find_hub_tracker.db.queries as queries_module
from find_hub_tracker.db.queries import (
    export_locations,
    get_all_latest_locations,
    get_device_history,
    get_last_location,
    prune_old_locations,
)
from find_hub_tracker.models import DeviceLocation


@pytest.fixture(autouse=True)
def frozen_utc_now(monkeypatch, base_time):
    """Freeze utc_now to BASE_TIME for every test, automatically."""
    monkeypatch.setattr(queries_module, "utc_now", lambda: base_time)


class TestGetLastLocation:
    def test_returns_none_when_no_locations(self, session, make_device):
        session.add(make_device(id="d1"))
        session.commit()

        assert get_last_location(session, "d1") is None

    def test_returns_none_for_unknown_device(self, session):
        assert get_last_location(session, "unknown") is None

    def test_returns_most_recent_by_polled_at(
        self, session, make_device, make_location, hours_ago
    ):
        session.add(make_device(id="d1"))
        session.add(make_location(device_id="d1", polled_at=hours_ago(5), latitude=1))
        session.add(make_location(device_id="d1", polled_at=hours_ago(0), latitude=2))
        session.add(make_location(device_id="d1", polled_at=hours_ago(2), latitude=3))
        session.commit()

        result = get_last_location(session, "d1")

        assert result.latitude == 2

    def test_ignores_other_devices(
        self, session, make_device, make_location, hours_ago
    ):
        session.add(make_device(id="d1"))
        session.add(make_device(id="d2"))
        session.add(make_location(device_id="d1", polled_at=hours_ago(1)))
        session.add(make_location(device_id="d2", polled_at=hours_ago(0)))
        session.commit()

        result = get_last_location(session, "d1")

        assert result.device_id == "d1"


class TestGetAllLatestLocations:
    def test_returns_empty_list_when_no_locations(self, session):
        assert get_all_latest_locations(session) == []

    def test_returns_one_row_per_device_with_latest_values(
        self, session, make_device, make_location, hours_ago
    ):
        session.add(make_device(id="d1"))
        session.add(make_device(id="d2"))
        session.add(make_location(device_id="d1", polled_at=hours_ago(5), latitude=1))
        session.add(make_location(device_id="d1", polled_at=hours_ago(0), latitude=2))
        session.add(make_location(device_id="d2", polled_at=hours_ago(3), latitude=9))
        session.add(make_location(device_id="d2", polled_at=hours_ago(1), latitude=8))
        session.commit()

        result = get_all_latest_locations(session)

        by_device = {loc.device_id: loc for loc in result}
        assert len(result) == 2
        assert by_device["d1"].latitude == 2
        assert by_device["d2"].latitude == 8

    def test_excludes_devices_with_no_locations(
        self, session, make_device, make_location, hours_ago
    ):
        session.add(make_device(id="d1"))
        session.add(make_device(id="d2"))  # no locations for this one
        session.add(make_location(device_id="d1", polled_at=hours_ago(0)))
        session.commit()

        result = get_all_latest_locations(session)

        assert [loc.device_id for loc in result] == ["d1"]

    def test_ordered_by_device_id(self, session, make_device, make_location, hours_ago):
        for device_id in ["zebra", "alpha", "mid"]:
            session.add(make_device(id=device_id))
            session.add(make_location(device_id=device_id, polled_at=hours_ago(0)))
        session.commit()

        result = get_all_latest_locations(session)

        assert [loc.device_id for loc in result] == ["alpha", "mid", "zebra"]


class TestGetDeviceHistory:
    def test_filters_to_requested_device(
        self, session, make_device, make_location, days_ago
    ):
        session.add(make_device(id="d1"))
        session.add(make_device(id="d2"))
        session.add(make_location(device_id="d1"))
        session.add(make_location(device_id="d2"))
        session.commit()

        result = get_device_history(session, "d1", days_ago(1), days_ago(-1))

        assert len(result) == 1
        assert result[0].device_id == "d1"

    def test_range_boundaries_are_inclusive(
        self, session, make_device, make_location, hours_ago
    ):
        session.add(make_device(id="d1"))
        start = hours_ago(2)
        end = hours_ago(0)
        session.add(make_location(device_id="d1", polled_at=start))  # exactly at start
        session.add(make_location(device_id="d1", polled_at=end))  # exactly at end
        session.commit()

        result = get_device_history(session, "d1", start, end)

        assert len(result) == 2

    def test_excludes_rows_outside_range(
        self, session, make_device, make_location, hours_ago
    ):
        session.add(make_device(id="d1"))
        session.add(make_location(device_id="d1", polled_at=hours_ago(10)))  # before
        session.add(make_location(device_id="d1", polled_at=hours_ago(1)))  # inside
        session.add(
            make_location(device_id="d1", polled_at=hours_ago(-10))
        )  # after (future)
        session.commit()

        result = get_device_history(session, "d1", hours_ago(5), hours_ago(0))

        assert len(result) == 1

    def test_ordered_descending_by_polled_at(
        self, session, make_device, make_location, hours_ago
    ):
        session.add(make_device(id="d1"))
        session.add(make_location(device_id="d1", polled_at=hours_ago(3), latitude=1))
        session.add(make_location(device_id="d1", polled_at=hours_ago(1), latitude=2))
        session.add(make_location(device_id="d1", polled_at=hours_ago(2), latitude=3))
        session.commit()

        result = get_device_history(session, "d1", hours_ago(5), hours_ago(0))

        assert [loc.latitude for loc in result] == [2, 3, 1]

    def test_returns_empty_list_for_no_matches(self, session, make_device, hours_ago):
        session.add(make_device(id="d1"))
        session.commit()

        result = get_device_history(session, "d1", hours_ago(5), hours_ago(0))

        assert result == []


class TestPruneOldLocations:
    def test_deletes_rows_older_than_cutoff(
        self, session, make_device, make_location, days_ago, monkeypatch
    ):
        session.add(make_device(id="d1"))
        old = make_location(device_id="d1", polled_at=days_ago(10))
        recent = make_location(device_id="d1", polled_at=days_ago(3))
        session.add(old)
        session.add(recent)
        session.commit()

        deleted_count = prune_old_locations(session, days=7)
        session.commit()

        assert deleted_count == 1
        remaining = session.exec(select(DeviceLocation)).all()
        assert len(remaining) == 1
        assert remaining[0].polled_at == recent.polled_at

    def test_boundary_row_exactly_at_cutoff_survives(
        self, session, make_device, make_location, days_ago, monkeypatch
    ):
        session.add(make_device(id="d1"))
        at_cutoff = make_location(device_id="d1", polled_at=days_ago(7))
        session.add(at_cutoff)
        session.commit()

        deleted_count = prune_old_locations(session, days=7)
        session.commit()

        assert deleted_count == 0
        assert session.get(DeviceLocation, at_cutoff.id) is not None

    def test_returns_number_of_deleted_rows(
        self, session, make_device, make_location, days_ago, monkeypatch
    ):
        session.add(make_device(id="d1"))
        for _ in range(3):
            session.add(make_location(device_id="d1", polled_at=days_ago(30)))
        session.commit()

        deleted_count = prune_old_locations(session, days=7)

        assert deleted_count == 3

    def test_does_not_autocommit(
        self, session, make_device, make_location, days_ago, monkeypatch
    ):
        """prune_old_locations documents that the caller is responsible
        for committing. Delete, roll back instead of committing, and
        confirm the row was never actually removed."""
        session.add(make_device(id="d1"))
        old = make_location(device_id="d1", polled_at=days_ago(30))
        session.add(old)
        session.commit()
        location_id = old.id

        prune_old_locations(session, days=7)
        session.rollback()

        assert session.get(DeviceLocation, location_id) is not None


class TestExportLocations:
    def test_no_filters_returns_all_ordered_chronologically(
        self, session, make_device, make_location, days_ago
    ):
        session.add(make_device(id="d1"))
        session.add(make_device(id="d2"))
        session.add(make_location(device_id="d1", polled_at=days_ago(0), latitude=2))
        session.add(make_location(device_id="d2", polled_at=days_ago(1), latitude=1))
        session.add(make_location(device_id="d1", polled_at=days_ago(-1), latitude=3))
        session.commit()

        result = export_locations(session)

        assert [loc.latitude for loc in result] == [1, 2, 3]

    def test_filtered_by_device(self, session, make_device, make_location, base_time):
        session.add(make_device(id="d1"))
        session.add(make_device(id="d2"))
        session.add(make_location(device_id="d1", polled_at=base_time))
        session.add(make_location(device_id="d2", polled_at=base_time))
        session.commit()

        result = export_locations(session, device_id="d1")

        assert len(result) == 1
        assert result[0].device_id == "d1"

    def test_filtered_by_days(
        self, session, make_device, make_location, days_ago, monkeypatch
    ):
        session.add(make_device(id="d1"))
        within_range = make_location(device_id="d1", polled_at=days_ago(2), latitude=1)
        outside_range = make_location(
            device_id="d1", polled_at=days_ago(10), latitude=2
        )
        session.add(within_range)
        session.add(outside_range)
        session.commit()

        result = export_locations(session, days=5)

        assert [loc.latitude for loc in result] == [1]

    def test_filtered_by_device_and_days_combined(
        self, session, make_device, make_location, days_ago, monkeypatch
    ):
        session.add(make_device(id="d1"))
        session.add(make_device(id="d2"))
        # Matches both filters
        session.add(make_location(device_id="d1", polled_at=days_ago(1), latitude=1))
        # Right device, but too old
        session.add(make_location(device_id="d1", polled_at=days_ago(10), latitude=2))
        # Recent, but wrong device
        session.add(make_location(device_id="d2", polled_at=days_ago(1), latitude=3))
        session.commit()

        result = export_locations(session, device_id="d1", days=5)

        assert [loc.latitude for loc in result] == [1]

    def test_returns_empty_list_when_no_locations(self, session):
        assert export_locations(session) == []
