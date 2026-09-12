"""Pydantic models for device data."""

from datetime import datetime
from typing import Self

from sqlmodel import SQLModel, Field, Index, Relationship

from find_hub_tracker.utils import utc_now
from find_hub_tracker.utils.geo import haversine_distance


class DeviceInfo(SQLModel, table=True):
    """A registered Find Hub device."""

    __tablename__ = "devices"

    id: str = Field(primary_key=True)
    name: str
    device_type: str = "unknown"  # phone, watch, buds, tracker, tablet, unknown
    model: str | None = None

    first_seen: datetime = Field(default_factory=utc_now)
    last_seen: datetime = Field(default_factory=utc_now)

    locations: list[DeviceLocation] = Relationship(
        back_populates="device",
    )
    alerts: list[BatteryAlert] = Relationship(back_populates="device")


class DeviceLocation(SQLModel, table=True):
    """A single device location reading."""

    __tablename__ = "device_locations"
    __table_args__ = (
        Index(
            "ix_device_location_device_polled",
            "device_id",
            "polled_at",
        ),
        Index("ix_location_polled", "polled_at"),
    )

    id: int | None = Field(default=None, primary_key=True)

    device_id: str = Field(foreign_key="devices.id")
    device: DeviceInfo = Relationship(back_populates="locations")

    latitude: float
    longitude: float
    accuracy_meters: float | None = None

    address: str | None = None
    battery_percent: int | None = None
    is_charging: bool | None = None

    timestamp: datetime = Field(default_factory=utc_now)
    polled_at: datetime = Field(default_factory=utc_now)

    @property
    def maps_url(self) -> str:
        """Google Maps URL for this location."""
        return f"https://www.google.com/maps?q={self.latitude},{self.longitude}"

    def distance_to(self, other: Self) -> float:
        return haversine_distance(
            self.latitude,
            self.longitude,
            other.latitude,
            other.longitude
        )


class BatteryAlert(SQLModel, table=True):
    """A battery alert event."""

    __tablename__ = "battery_alerts"
    __table_args__ = (
        Index(
            "ix_battery_alert_device_time",
            "device_id",
            "alert_time",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)

    device_id: str = Field(foreign_key="devices.id")
    device: DeviceInfo = Relationship(back_populates="alerts")

    battery_percent: int
    is_critical: bool = False
    alert_time: datetime = Field(default_factory=utc_now)


class ServiceHeartBeat(SQLModel, table=True):
    """A heartbeat record for the service."""

    __tablename__ = "service_heartbeats"

    service_name: str = Field(primary_key=True)
    host: str = Field(primary_key=True)

    last_heartbeat: datetime = Field(default_factory=utc_now)
    poll_count: int = 0
    error_count: int = 0
    started_at: datetime = Field(default_factory=utc_now)
    version: str | None = None
