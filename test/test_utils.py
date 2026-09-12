from datetime import timedelta

import pytest

# Assumption: these live alongside find_hub_tracker.utils.geo. Adjust this
# import if the real module path differs (e.g. a bot-specific formatting
# module) — nothing else in this file depends on the exact path.
from find_hub_tracker import utils
from find_hub_tracker.utils import format_distance, relative_time
from find_hub_tracker.utils.geo import haversine_distance


class _FrozenNow:
    """Minimal stand-in for the `datetime` name imported into the
    formatting module. Only implements `.now(tz)`, matching the only
    thing relative_time actually calls on it.
    """

    def __init__(self, when):
        self.when = when

    def now(self, tz=None):
        if tz is None:
            # Mirror real datetime.now(None): naive local time. Since our
            # frozen instant is timezone-aware, drop the tzinfo rather
            # than converting, so naive-input tests stay naive-vs-naive.
            return self.when.replace(tzinfo=None)
        return self.when.astimezone(tz)


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch, base_time):
    """Freeze the `datetime` reference inside the formatting module to
    base_time for every test in this file, so relative_time's internal
    `datetime.now(dt.tzinfo)` call is deterministic. Scoped to this file
    only — see the discussion in test_queries_locations.py's
    frozen_utc_now for why this is a per-file fixture rather than global.
    """
    monkeypatch.setattr(utils, "datetime", _FrozenNow(base_time))


class TestHaversineDistance:
    def test_same_point_is_zero(self):
        assert haversine_distance(40.7128, -74.0060, 40.7128, -74.0060) == 0

    def test_order_independent(self):
        """Distance should be symmetric regardless of argument order."""
        a = (40.7128, -74.0060)
        b = (34.0522, -118.2437)

        d_ab = haversine_distance(*a, *b)
        d_ba = haversine_distance(*b, *a)

        assert d_ab == pytest.approx(d_ba)

    def test_new_york_to_los_angeles(self):
        # ~3,935,746 m great-circle distance (R=6371 km)
        result = haversine_distance(40.7128, -74.0060, 34.0522, -118.2437)
        assert result == pytest.approx(3_935_746, rel=0.01)

    def test_london_to_paris(self):
        # ~343,556 m, useful as a "short distance" sanity check
        result = haversine_distance(51.5074, -0.1278, 48.8566, 2.3522)
        assert result == pytest.approx(343_556, rel=0.01)

    def test_quarter_of_earth_circumference(self):
        """Equator point to the North Pole is exactly a quarter of the
        great-circle circumference (~10,007,543 m for R=6371 km)."""
        result = haversine_distance(0, 0, 90, 0)
        assert result == pytest.approx(10_007_543, rel=0.01)

    def test_antipodal_points(self):
        """Antipodal points are the maximum possible distance: half the
        great-circle circumference (~20,015,087 m for R=6371 km)."""
        result = haversine_distance(0, 0, 0, 180)
        assert result == pytest.approx(20_015_087, rel=0.01)

    def test_small_distance_is_nonzero_and_small(self):
        """Two nearby points (~0.001 degree latitude apart, roughly a
        city block) should give a small but strictly positive distance in
        meters — guarding against a function that only works at large
        scales, rounds small values to zero, or silently returns km."""
        result = haversine_distance(40.7128, -74.0060, 40.7138, -74.0060)
        assert result == pytest.approx(111.2, rel=0.02)


class TestFormatDistance:
    def test_zero_is_meters(self):
        assert format_distance(0) == "0m"

    def test_typical_meters_value(self):
        assert format_distance(500) == "500m"

    def test_meters_rounds_to_nearest_integer(self):
        assert format_distance(499.6) == "500m"

    def test_just_under_1000_that_rounds_up_stays_in_meters(self):
        """499.6 rounds normally, but 999.9 is a sharper edge case: it's
        still < 1000 (so takes the meters branch) yet formats to "1000m"
        rather than switching to km. This documents the function's
        actual behavior at that seam rather than asserting what it
        "should" do."""
        assert format_distance(999.9) == "1000m"

    def test_exactly_1000_switches_to_km(self):
        assert format_distance(1000) == "1.0km"

    def test_just_under_1000_stays_meters(self):
        assert format_distance(999) == "999m"

    def test_km_formatted_to_one_decimal(self):
        assert format_distance(1500) == "1.5km"
        assert format_distance(2000) == "2.0km"

    def test_large_km_value_has_no_thousands_separator(self):
        """Documents current behavior: large distances aren't grouped
        (e.g. "1000.0km", not "1,000.0km")."""
        assert format_distance(999_999) == "1000.0km"

    def test_negative_distance_uses_meters_branch(self):
        """Not a value we expect in practice, but negative < 1000 is
        still True, so this documents the function's actual (unguarded)
        behavior rather than assuming it raises or clamps."""
        assert format_distance(-5) == "-5m"


class TestRelativeTime:
    def test_under_a_minute_is_just_now(self, base_time):
        dt = base_time - timedelta(seconds=30)

        assert relative_time(dt) == "just now"

    def test_boundary_59_seconds_is_still_just_now(self, base_time):
        dt = base_time - timedelta(seconds=59)

        assert relative_time(dt) == "just now"

    def test_boundary_60_seconds_switches_to_minutes(self, minutes_ago):
        assert relative_time(minutes_ago(1)) == "1m ago"

    def test_fractional_seconds_truncate_not_round(self, base_time):
        """int(delta.total_seconds()) truncates toward zero rather than
        rounding, so 59.9s stays in the "just now" bucket rather than
        rounding up to 60s / "1m ago"."""
        dt = base_time - timedelta(seconds=59, milliseconds=900)

        assert relative_time(dt) == "just now"

    def test_minutes_ago(self, minutes_ago):
        assert relative_time(minutes_ago(5)) == "5m ago"

    def test_boundary_59_minutes_59_seconds_is_still_minutes(self, base_time):
        dt = base_time - timedelta(seconds=3599)

        assert relative_time(dt) == "59m ago"

    def test_boundary_3600_seconds_switches_to_hours(self, hours_ago):
        assert relative_time(hours_ago(1)) == "1h ago"

    def test_hours_ago(self, hours_ago):
        assert relative_time(hours_ago(2)) == "2h ago"

    def test_boundary_23_hours_59_minutes_is_still_hours(self, base_time):
        dt = base_time - timedelta(seconds=86399)

        assert relative_time(dt) == "23h ago"

    def test_boundary_86400_seconds_switches_to_days(self, days_ago):
        assert relative_time(days_ago(1)) == "1d ago"

    def test_days_ago(self, days_ago):
        assert relative_time(days_ago(3)) == "3d ago"

    def test_many_days_ago(self, days_ago):
        assert relative_time(days_ago(10)) == "10d ago"

    def test_future_timestamp_reads_as_just_now(self, minutes_ago):
        """dt in the future gives a negative delta. seconds < 60 is still
        True for negative numbers, so this documents current (unguarded)
        behavior rather than assuming the function rejects future
        timestamps."""
        assert relative_time(minutes_ago(-5)) == "just now"

    def test_naive_datetime_input_is_supported(self, minutes_ago):
        """dt.tzinfo is None here, so relative_time calls
        datetime.now(None) internally — this should behave the same as
        the tz-aware case, not raise a naive/aware comparison error."""
        dt = minutes_ago(10).replace(tzinfo=None)

        assert relative_time(dt) == "10m ago"
