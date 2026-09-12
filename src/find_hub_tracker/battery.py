"""Battery monitoring and alert logic.

NOTE: GoogleFindMyTools does NOT currently provide battery data.
This module is structured to work once battery data becomes available
upstream. Until then, battery_percent will always be None and no alerts
will fire.
"""

from datetime import timedelta

import structlog

from find_hub_tracker.models import BatteryAlert, DeviceInfo, DeviceLocation
from find_hub_tracker.utils import utc_now

log = structlog.get_logger()

# Device types considered wearables (get lower alert thresholds)
WEARABLE_TYPES = {"watch", "buds"}


class BatteryMonitor:
    """Monitors device battery levels and sends alerts when thresholds are crossed."""

    def __init__(
        self,
        low_threshold: int = 20,
        critical_threshold: int = 10,
        wearable_offset: int = 5,
        cooldown_minutes: int = 60,
    ) -> None:
        self.low_threshold = low_threshold
        self.critical_threshold = critical_threshold
        self.wearable_offset = wearable_offset
        self.cooldown = timedelta(minutes=cooldown_minutes)

    def check(
        self,
        device: DeviceInfo,
        location: DeviceLocation,
        last_alert: BatteryAlert | None = None,
    ) -> BatteryAlert | None:
        if location.battery_percent is None:
            return None

        is_low, is_critical = self._check_battery_level(device, location)

        if not is_low:
            return None

        # check cooldown
        now = utc_now()
        time_since_last_alert = (now - last_alert.alert_time) if last_alert else None
        if time_since_last_alert and time_since_last_alert < self.cooldown:
            log.debug(
                "alert_cooldown",
                device=device.name,
                last_alert_mins_ago=int(time_since_last_alert.total_seconds() / 60),
            )
            return None

        return BatteryAlert(
            device_id=device.id,
            battery_percent=location.battery_percent,
            is_critical=is_critical,
            alert_time=now,
        )

    def _check_battery_level(
        self, device: DeviceInfo, loc: DeviceLocation
    ) -> tuple[bool, bool]:
        low, critical = self._thresholds_for(device.device_type)

        is_critical = loc.battery_percent <= critical
        is_low = loc.battery_percent <= low

        return is_low, is_critical

    def _thresholds_for(self, device_type: str) -> tuple[int, int]:
        """Return (low, critical) thresholds, adjusted for wearables."""
        if device_type.lower() in WEARABLE_TYPES:
            return (
                self.low_threshold + self.wearable_offset,
                self.critical_threshold + self.wearable_offset,
            )
        return (self.low_threshold, self.critical_threshold)
