import functools
from contextlib import contextmanager
from datetime import timedelta
from typing import Awaitable, Callable

import structlog

from find_hub_tracker.battery import BatteryMonitor
from find_hub_tracker.config import Settings
from find_hub_tracker.db import queries
from find_hub_tracker.db.core import get_engine, get_session, run_migrations
from find_hub_tracker.discord import DiscordPublisher
from find_hub_tracker.google_fmd import GoogleFindMyDevices
from find_hub_tracker.heartbeat import (
    make_heartbeat,
    ping_healthchecks,
)
from find_hub_tracker.models import DeviceInfo, DeviceLocation
from find_hub_tracker.scheduler import Scheduler

log = structlog.get_logger()

SIGNIFICANT_MOVE_METERS = 100.0


def has_moved_significantly(prev: DeviceLocation | None, cur: DeviceLocation) -> bool:
    """Determine if the device has moved significantly since the last known location."""
    if prev is None:
        return True  # No previous location, so consider it significant

    return cur.distance_to(prev) >= SIGNIFICANT_MOVE_METERS


def handle_error[F: Callable[..., Awaitable[None]]](
    event: str,
    *,
    on_error: Callable[["App"], Awaitable[None]] | None = None,
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            try:
                return await func(self, *args, **kwargs)
            except Exception:
                log.exception(event)
                if on_error is not None:
                    await on_error(self)

        return wrapper

    return decorator


class App:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.fmd = GoogleFindMyDevices(
            auth_dir=str(settings.auth_secrets_path).rsplit("/", 1)[0]
        )
        self.publisher = DiscordPublisher(
            webhook_url=settings.discord_webhook_url,
            battery_webhook_url=settings.battery_webhook_url,
        )
        self.battery_monitor = BatteryMonitor(
            low_threshold=settings.battery_low_threshold_percent,
            critical_threshold=settings.battery_critical_threshold_percent,
            wearable_offset=settings.wearable_threshold_offset,
            cooldown_minutes=settings.alert_cooldown_minutes,
        )
        self._poll_count = 0
        self._error_count = 0
        self._scheduler = Scheduler()
        self._db_engine = get_engine(self.settings)

    @contextmanager
    def get_db(self, *, commit: bool = False):
        with get_session(self._db_engine, commit=commit) as session:
            yield session

    async def start(self) -> None:
        run_migrations(self._db_engine)

        log.info(
            "app_starting",
            poll_interval=self.settings.poll_interval_seconds,
            battery_interval=self.settings.battery_check_interval_seconds,
            summary_interval_hours=self.settings.summary_interval_hours,
            devices_filter=self.settings.devices_to_track or "all",
        )

        # Periodic tasks

        self._scheduler.run_every(
            self.poll_locations,
            interval=timedelta(seconds=self.settings.poll_interval_seconds),
            id="poll_locations",
        )

        self._scheduler.run_every(
            self.check_batteries,
            interval=timedelta(seconds=self.settings.battery_check_interval_seconds),
            id="battery_check",
        )

        self._scheduler.run_every(
            self.post_summary,
            interval=timedelta(hours=self.settings.summary_interval_hours),
            id="summary_post",
        )

        self._scheduler.run_every(
            self.prune_history, interval=timedelta(hours=24), id="history_prune"
        )

        # Post-startup tasks

        self._scheduler.run_once(
            self.post_startup,
            id="post_startup",
        )

        # Cleanup

        self._scheduler.on_shutdown(self.shutdown)

        # Run

        await self._scheduler.run()

    async def post_startup(self):
        devices = await self.fmd.list_devices()
        await self.publisher.post_startup(len(devices))

    async def shutdown(self):
        log.debug("shutdown_initiated")
        await self.publisher.post_shutdown()
        await self.publisher.close()
        self._db_engine.dispose()
        log.info("shutdown_complete")

    async def _fetch_locations(
        self,
    ) -> tuple[list[DeviceInfo], list[DeviceLocation]]:
        device_filter = self.settings.devices_to_track_list or None

        log.debug("get_all_locations", device_filter=device_filter)

        locations = await self.fmd.get_all_locations(device_filter)

        if not locations:
            log.warning("no_locations_returned")
            return [], []

        devices = await self.fmd.list_devices()  # cached

        log.info("poll_cycle", devices_found=len(locations))

        return devices, locations

    @handle_error("poll_cycle_error", on_error=lambda self: self._handle_poll_failure())
    async def poll_locations(self) -> None:
        devices, locations = await self._fetch_locations()

        events = self._persist_poll(devices, locations)

        await self._publish_location_events(events)

        await ping_healthchecks(
            self.settings.healthchecks_ping_url,
            success=True,
        )

    def _persist_poll(
        self,
        devices: list[DeviceInfo],
        locations: list[DeviceLocation],
    ) -> list[tuple[DeviceLocation, DeviceLocation | None]]:
        location_events = []
        next_poll_count = self._poll_count + 1

        with self.get_db(commit=True) as db:
            for device in devices:
                queries.upsert_device(db, device)

            last_by_device_id = {
                loc.device_id: loc for loc in queries.get_all_latest_locations(db)
            }

            for location in locations:
                previous = last_by_device_id.get(location.device_id)
                location_events.append((location, previous))

                db.add(location)

            heartbeat = make_heartbeat(
                poll_count=next_poll_count,
                error_count=self._error_count,
            )
            queries.upsert_heartbeat(db, heartbeat)

        self._poll_count = next_poll_count

        return location_events

    async def _publish_location_events(
        self,
        location_events: list[tuple[DeviceLocation, DeviceLocation | None]],
    ) -> None:
        for location, previous in location_events:
            if not has_moved_significantly(previous, location):
                continue

            await self.publisher.post_location_update(location, previous)

    async def _handle_poll_failure(self) -> None:
        self._error_count += 1

        try:
            with self.get_db(commit=True) as db:
                heartbeat = make_heartbeat(
                    poll_count=self._poll_count,
                    error_count=self._error_count,
                )
                queries.upsert_heartbeat(db, heartbeat)
        except Exception:
            log.warning("heartbeat_record_failed", exc_info=True)

        await ping_healthchecks(
            self.settings.healthchecks_ping_url,
            success=False,
        )

    @handle_error("battery_check_error")
    async def check_batteries(self) -> None:
        """Check battery levels for all tracked devices."""
        alerts = []

        with self.get_db() as db:
            candidates = queries.get_battery_check_data(db)

            for device, location, last_alert in candidates:
                alert = self.battery_monitor.check(device, location, last_alert)
                if alert:
                    db.add(alert)
                    alerts.append(alert)

        for alert in alerts:
            await self.publisher.post_battery_alert(alert)

        if alerts:
            log.info("battery_alerts_sent", count=len(alerts))

    @handle_error("summary_error")
    async def post_summary(self) -> None:
        """Post a periodic summary of all device locations to Discord."""
        with self.get_db() as db:
            latest = queries.get_all_latest_locations(db)

        if latest:
            await self.publisher.post_summary(latest)
            log.info("summary_posted", devices=len(latest))

    @handle_error("prune_error")
    async def prune_history(self) -> None:
        """Prune old location records based on retention settings."""
        days = self.settings.history_retention_days

        with self.get_db() as db:
            count = queries.prune_old_locations(db, days)

        if count > 0:
            log.info("history_pruned", records_deleted=count, older_than_days=days)
