from find_hub_tracker.db.queries import get_all_devices, upsert_device
from find_hub_tracker.models import DeviceInfo


class TestUpsertDevice:
    def test_inserts_when_absent(self, session, make_device):
        device = make_device(id="d1", name="Pixel 9")

        result = upsert_device(session, device)
        session.commit()

        assert result is device
        stored = session.get(DeviceInfo, "d1")
        assert stored.name == "Pixel 9"

    def test_updates_mutable_fields_when_present(self, session, make_device):
        original = make_device(
            id="d1", name="Old Name", device_type="phone", model="Pixel 8"
        )
        session.add(original)
        session.commit()

        incoming = make_device(
            id="d1", name="New Name", device_type="tablet", model="Pixel Tablet"
        )

        upsert_device(session, incoming)
        session.commit()

        stored = session.get(DeviceInfo, "d1")
        assert stored.name == "New Name"
        assert stored.device_type == "tablet"
        assert stored.model == "Pixel Tablet"

    def test_updates_last_seen(self, session, make_device, hours_ago):
        original = make_device(id="d1", last_seen=hours_ago(5))
        session.add(original)
        session.commit()

        incoming = make_device(id="d1", last_seen=hours_ago(0))
        upsert_device(session, incoming)
        session.commit()

        stored = session.get(DeviceInfo, "d1")
        assert stored.last_seen == hours_ago(0)

    def test_preserves_first_seen_on_update(self, session, make_device, hours_ago):
        original = make_device(id="d1", first_seen=hours_ago(48))
        session.add(original)
        session.commit()

        # An incoming record with a different (later) first_seen should
        # NOT overwrite the original — first_seen is meant to be the
        # earliest time the device was ever recorded.
        incoming = make_device(id="d1", first_seen=hours_ago(1))
        upsert_device(session, incoming)
        session.commit()

        stored = session.get(DeviceInfo, "d1")
        assert stored.first_seen == hours_ago(48)

    def test_returns_the_persisted_instance_on_update(self, session, make_device):
        """The returned object should be the one already attached to the
        session (so callers can keep using it), not the new transient
        object that was passed in."""
        original = make_device(id="d1", name="Original")
        session.add(original)
        session.commit()

        incoming = make_device(id="d1", name="Updated")
        result = upsert_device(session, incoming)

        assert result is original
        assert result is not incoming

    def test_does_not_autocommit(self, session_maker, make_device):
        device = make_device(id="d1")
        with session_maker() as session:
            upsert_device(session, device)

        with session_maker() as session:
            assert session.get(DeviceInfo, "d1") is None


class TestGetAllDevices:
    def test_returns_empty_list_when_no_devices(self, session):
        assert get_all_devices(session) == []

    def test_returns_devices_ordered_by_name(self, session, make_device):
        session.add(make_device(id="d1", name="Zebra Phone"))
        session.add(make_device(id="d2", name="Alpha Watch"))
        session.add(make_device(id="d3", name="Mid Tablet"))
        session.commit()

        result = get_all_devices(session)

        assert [d.name for d in result] == ["Alpha Watch", "Mid Tablet", "Zebra Phone"]
