import pytest

from find_hub_tracker.utils.geo import haversine_distance


class TestMapsUrl:
    def test_format_with_positive_coordinates(self, make_location):
        location = make_location(device_id="d1", latitude=40.7128, longitude=-74.0060)
        assert location.maps_url == "https://www.google.com/maps?q=40.7128,-74.006"

    def test_format_with_negative_latitude(self, make_location):
        location = make_location(device_id="d1", latitude=-33.8688, longitude=151.2093)
        assert location.maps_url == "https://www.google.com/maps?q=-33.8688,151.2093"

    def test_format_with_zero_coordinates(self, make_location):
        location = make_location(device_id="d1", latitude=0.0, longitude=0.0)
        assert location.maps_url == "https://www.google.com/maps?q=0.0,0.0"


class TestDistanceTo:
    def test_distance_to_self_is_zero(self, make_location):
        location = make_location(device_id="d1", latitude=40.7128, longitude=-74.0060)
        assert location.distance_to(location) == 0

    def test_distance_to_identical_coordinates_is_zero(self, make_location):
        a = make_location(device_id="d1", latitude=48.8566, longitude=2.3522)
        b = make_location(device_id="d2", latitude=48.8566, longitude=2.3522)
        assert a.distance_to(b) == 0

    def test_delegates_to_haversine_distance(self, make_location):
        """distance_to should just forward to haversine_distance with this
        location's and the other's lat/lng — not reimplement the math.
        (Full accuracy coverage against known city pairs lives in
        test_geo.py; here we only check the delegation is correct.)"""
        nyc = make_location(device_id="d1", latitude=40.7128, longitude=-74.0060)
        la = make_location(device_id="d2", latitude=34.0522, longitude=-118.2437)

        expected = haversine_distance(
            nyc.latitude, nyc.longitude, la.latitude, la.longitude
        )

        assert nyc.distance_to(la) == pytest.approx(expected)

    def test_distance_is_symmetric(self, make_location):
        a = make_location(device_id="d1", latitude=51.5074, longitude=-0.1278)
        b = make_location(device_id="d2", latitude=48.8566, longitude=2.3522)

        assert a.distance_to(b) == pytest.approx(b.distance_to(a))
