from datetime import datetime, timedelta

from sqlmodel import Session, func, select

from find_hub_tracker.models import (
    BatteryAlert,
    DeviceInfo,
    DeviceLocation,
    ServiceHeartBeat,
)
from find_hub_tracker.utils import utc_now


def upsert_device(session: Session, device: DeviceInfo) -> DeviceInfo:
    existing = session.get(DeviceInfo, device.id)

    if existing is None:
        session.add(device)
        return device

    existing.name = device.name
    existing.device_type = device.device_type
    existing.model = device.model
    existing.last_seen = device.last_seen
    # do not update first_seen

    return existing


def get_all_devices(session: Session) -> list[DeviceInfo]:
    statement = select(DeviceInfo).order_by(DeviceInfo.name)
    return list(session.exec(statement))


def get_last_location(session: Session, device_id: str) -> DeviceLocation | None:
    """Returns the most recently polled location for a device."""
    statement = (
        select(DeviceLocation)
        .where(DeviceLocation.device_id == device_id)
        .order_by(DeviceLocation.polled_at.desc())
        .limit(1)
    )
    return session.exec(statement).first()


def get_all_latest_locations(session: Session) -> list[DeviceLocation]:
    """Return the most recent location for every device."""
    ranked = select(
        DeviceLocation,
        func.row_number()
        .over(
            partition_by=DeviceLocation.device_id,
            order_by=DeviceLocation.polled_at.desc(),
        )
        .label("row_number"),
    ).subquery()

    statement = (
        select(DeviceLocation)
        .join(
            ranked,
            DeviceLocation.id == ranked.c.id,
        )
        .where(ranked.c.row_number == 1)
        .order_by(DeviceLocation.device_id)
    )

    return list(session.exec(statement))


def get_device_history(
    session: Session, device_id: str, start: datetime, end: datetime
) -> list[DeviceLocation]:
    """Return location history for a device within a time range"""
    statement = (
        select(DeviceLocation)
        .where(
            DeviceLocation.device_id == device_id,
            DeviceLocation.polled_at >= start,
            DeviceLocation.polled_at <= end,
        )
        .order_by(DeviceLocation.polled_at.desc())
    )

    return list(session.exec(statement))


def prune_old_locations(session: Session, days: int) -> int:
    """Delete location records older than given number of days.

    Returns number of deleted records.

    Caller is responsible for committing the transaction."""
    cutoff = utc_now() - timedelta(days=days)

    statement = select(DeviceLocation).where(DeviceLocation.polled_at < cutoff)
    locations = list(session.exec(statement))

    for location in locations:
        session.delete(location)

    return len(locations)


def export_locations(
    session: Session, device_id: str | None = None, days: int | None = None
) -> list[DeviceLocation]:
    """Return location records for export, ordered chronologically."""
    statement = select(DeviceLocation)

    if device_id is not None:
        statement = statement.where(DeviceLocation.device_id == device_id)

    if days is not None:
        cutoff = utc_now() - timedelta(days=days)
        statement = statement.where(DeviceLocation.polled_at >= cutoff)

    statement = statement.order_by(DeviceLocation.polled_at)

    return list(session.exec(statement))


def get_last_alert(session: Session, device_id: str) -> BatteryAlert | None:
    """Returns the most recent battery alert for a device."""
    statement = (
        select(BatteryAlert)
        .where(BatteryAlert.device_id == device_id)
        .order_by(BatteryAlert.alert_time.desc())
        .limit(1)
    )

    return session.exec(statement).first()


def upsert_heartbeat(session: Session, heartbeat: ServiceHeartBeat) -> ServiceHeartBeat:
    existing = get_heartbeat(session, heartbeat.service_name, heartbeat.host)

    if existing is None:
        session.add(heartbeat)
        return heartbeat

    existing.last_heartbeat = heartbeat.last_heartbeat
    existing.poll_count = heartbeat.poll_count
    existing.error_count = heartbeat.error_count
    existing.version = heartbeat.version
    # do not update started_at

    return existing


def get_heartbeat(
    session: Session, service_name: str, host: str
) -> ServiceHeartBeat | None:
    """Return the heartbeat record for a service/host pair."""
    return session.get(ServiceHeartBeat, (service_name, host))


def get_all_latest_battery_alerts(
    session: Session,
) -> list[BatteryAlert]:
    latest = (
        select(
            BatteryAlert.device_id,
            func.max(BatteryAlert.alert_time).label("max_alert_time"),
        )
        .group_by(BatteryAlert.device_id)
        .subquery()
    )

    statement = select(BatteryAlert).join(
        latest,
        (latest.c.device_id == BatteryAlert.device_id)
        & (latest.c.max_alert_time == BatteryAlert.alert_time),
    )

    return list(session.exec(statement))


def get_battery_check_data(
    session: Session,
) -> list[tuple[DeviceInfo, DeviceLocation, BatteryAlert | None]]:
    """Return the latest location and latest alert for each device."""
    latest_locations = get_all_latest_locations(session)

    last_alerts = {
        alert.device_id: alert for alert in get_all_latest_battery_alerts(session)
    }

    return [
        (location.device, location, last_alerts.get(location.device_id))
        for location in latest_locations
    ]
