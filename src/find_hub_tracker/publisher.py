"""Telegram Bot API publisher for location updates and battery alerts."""

import asyncio

import httpx
import structlog

from find_hub_tracker.models import BatteryAlert, DeviceInfo, DeviceLocation
from find_hub_tracker.utils import format_distance, relative_time

log = structlog.get_logger()

TELEGRAM_API_BASE = "https://api.telegram.org"

# Emoji used in place of Discord embed colors
EMOJI_LOCATION = "\U0001f4cd"
EMOJI_SUMMARY = "\U0001f4ca"
EMOJI_BATTERY_LOW = "\U0001f50b"
EMOJI_BATTERY_CRITICAL = "\U0001faab"
EMOJI_STARTUP = "\u2705"
EMOJI_SHUTDOWN = "\u26d4"
EMOJI_TEST = "\U0001f9ea"


class TelegramPublisher:
    """Publishes device updates to a single Telegram chat via the Bot API.

    Send-only: this does not listen for incoming updates, so there's no
    inbound-message surface to whitelist. If you later add a webhook or
    long-polling loop to handle commands (e.g. /status), check the
    incoming `chat_id` against an allowlist there before acting on it.
    """

    def __init__(self, bot_token: str | None, chat_id: str | int | None) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._client = httpx.AsyncClient(
            base_url=f"{TELEGRAM_API_BASE}/bot{bot_token}",
            timeout=30.0,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def post_location_update(
        self,
        location: DeviceLocation,
        previous: DeviceLocation | None = None,
    ) -> bool:
        """Post a location update message."""
        lines = [
            f"{EMOJI_LOCATION} <b>{_esc(location.device.name)} moved</b>",
            "",
            f"<b>Location:</b> "
            f'<a href="{location.maps_url}">{location.latitude:.6f}, {location.longitude:.6f}</a>',
        ]

        if location.accuracy_meters is not None:
            lines.append(f"<b>Accuracy:</b> {location.accuracy_meters:.0f}m")

        if location.battery_percent is not None:
            charging = " (charging)" if location.is_charging else ""
            lines.append(f"<b>Battery:</b> {location.battery_percent}%{charging}")

        if previous:
            dist = location.distance_to(previous)
            lines.append(f"<b>Distance Moved:</b> {format_distance(dist)}")

        lines.append(f"<i>Updated {relative_time(location.timestamp)}</i>")

        return await self._send_message("\n".join(lines))

    async def post_summary(
        self, devices: list[DeviceInfo], locations: list[DeviceLocation]
    ) -> bool:
        """Post a periodic summary message showing all device locations."""
        if not locations:
            return False

        devices_by_id = {d.id: d for d in devices}

        lines = [f"{EMOJI_SUMMARY} <b>Device Location Summary</b>", ""]
        for loc in locations:
            device = devices_by_id.get(loc.device_id)
            device_name = device.name if device else "<unknown-name>"
            battery = (
                f" | {loc.battery_percent}%" if loc.battery_percent is not None else ""
            )
            lines.append(
                f'\u2022 <a href="{loc.maps_url}">{_esc(device_name)}</a>'
                f" ({loc.latitude:.4f}, {loc.longitude:.4f}){battery}"
                f" | {relative_time(loc.timestamp)}"
            )
        lines.append("")
        lines.append("<i>Next summary in 6 hours</i>")

        return await self._send_message("\n".join(lines))

    async def post_battery_alert(self, alert: BatteryAlert) -> bool:
        """Post a battery alert message."""
        if alert.is_critical:
            emoji = EMOJI_BATTERY_CRITICAL
            label = "Critical Battery"
        else:
            emoji = EMOJI_BATTERY_LOW
            label = "Low Battery"

        lines = [
            f"{emoji} <b>{label}: {_esc(alert.device_name)}</b>",
            "",
            f"<b>Battery Level:</b> {alert.battery_percent}%",
            f"<b>Device Type:</b> {_esc(alert.device_type.title())}",
        ]

        return await self._send_message("\n".join(lines))

    async def post_startup(self, devices: list[DeviceInfo]) -> bool:
        """Post a service startup message."""
        devices_str = "\n".join([f"\u2022 {d.name}" for d in devices])
        text = (
            f"{EMOJI_STARTUP} <b>Find Hub Tracker Started</b>\n\n"
            f"Tracking <b>{len(devices)}</b> device(s). Polling active.\n\n"
            f"{devices_str}"
        )
        return await self._send_message(text)

    async def post_shutdown(self) -> bool:
        """Post a service shutdown message."""
        text = f"{EMOJI_SHUTDOWN} <b>Find Hub Tracker Stopped</b>\n\nService is shutting down gracefully."
        return await self._send_message(text)

    async def post_test(self) -> bool:
        """Send a test message to verify bot configuration."""
        text = (
            f"{EMOJI_TEST} <b>Test Message</b>\n\nTelegram bot is configured correctly!"
        )
        return await self._send_message(text)

    async def _send_message(self, text: str) -> bool:
        """Send a message to the configured chat with exponential backoff on 429."""
        if self.chat_id is None:
            return False

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                resp = await self._client.post("/sendMessage", json=payload)
                if resp.status_code == 429:
                    retry_after = (
                        resp.json()
                        .get("parameters", {})
                        .get("retry_after", 2 ** (attempt + 1))
                    )
                    log.warning(
                        "telegram_rate_limited",
                        retry_after=retry_after,
                        attempt=attempt + 1,
                    )
                    if attempt < max_retries:
                        await asyncio.sleep(retry_after)
                        continue
                    return False
                resp.raise_for_status()
                body = resp.json()
                if not body.get("ok", False):
                    log.error("telegram_api_error", response=body)
                    return False
                log.debug("telegram_message_sent", status=resp.status_code)
                return True
            except httpx.HTTPError:
                log.exception("telegram_send_error", attempt=attempt + 1)
                if attempt < max_retries:
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                return False
        return False


def _esc(text: str) -> str:
    """Escape HTML special characters for Telegram's HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
