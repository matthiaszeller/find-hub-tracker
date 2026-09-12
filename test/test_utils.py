import pytest

from find_hub_tracker.utils.geo import haversine_distance


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
