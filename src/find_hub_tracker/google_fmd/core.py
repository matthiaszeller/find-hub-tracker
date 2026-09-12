"""Wrapper around GoogleFindMyTools for querying Google Find Hub devices.

GoogleFindMyTools (https://github.com/leonboe1/GoogleFindMyTools) reverse-engineers
Google's Nova/Spot API to query Find Hub device locations and decrypt E2EE location data.

Auth is handled via a one-time Chrome login that produces an Auth/secrets.json file.
After that, the service runs headlessly.

NOTE: Battery level data is NOT currently supported by GoogleFindMyTools.
The battery_percent and is_charging fields will always be None.
This infrastructure exists so battery monitoring works automatically when
upstream adds support.
"""

import asyncio
from pathlib import Path

import structlog

from find_hub_tracker.models import DeviceInfo, DeviceLocation

from ..utils.cache import AsyncTTLCache
from .device import list_devices
from .location import (
    LocationRequestError,
    LocationRequestTimeout,
    get_location_data_for_device,
    parse_location_output,
)

log = structlog.get_logger()

# Location status mapping from GoogleFindMyTools integer codes
_LOCATION_STATUS_MAP = {
    0: "semantic",
    1: "last_known",
    2: "crowdsourced",
    3: "aggregated",
}


class AuthError(Exception):
    """Raised when Google authentication is missing or invalid."""


class GoogleFindMyDevices:
    """Interface to Google Find Hub via GoogleFindMyTools.

    This class wraps the GoogleFindMyTools library to provide a clean async API
    for listing devices and retrieving their locations.
    """

    def __init__(self, auth_dir: str = "Auth") -> None:
        self.auth_dir = Path(auth_dir)
        self._devices_cache: AsyncTTLCache[list[DeviceInfo]] = AsyncTTLCache(ttl=30)
        self._cache_time: float = 0
        self._cache_ttl: float = 300
        self._gfmt_available = False
        self._init_gfmt()

    def _init_gfmt(self) -> None:
        """Check if GoogleFindMyTools modules are importable."""
        try:
            import importlib.util

            self._gfmt_available = (
                importlib.util.find_spec("NovaApi") is not None
                and importlib.util.find_spec("ProtoDecoders") is not None
            )
            if self._gfmt_available:
                log.info("googlefindmytools_available")
        except ImportError:
            self._gfmt_available = False

        if not self._gfmt_available:
            log.warning(
                "googlefindmytools_unavailable",
                hint="Ensure GoogleFindMyTools is on sys.path or vendored",
            )

    def _check_auth(self) -> None:
        """Verify that auth secrets exist."""
        secrets_file = self.auth_dir / "secrets.json"
        if not secrets_file.exists():
            raise AuthError(
                f"Auth secrets not found at {secrets_file}. "
                "Run 'find-hub-tracker auth' to authenticate with Google first."
            )

    def _check_available(self) -> None:
        """Verify GoogleFindMyTools is importable."""
        if not self._gfmt_available:
            raise RuntimeError(
                "GoogleFindMyTools is not installed or not on sys.path. "
                "Clone it and add its directory to PYTHONPATH, or vendor the modules."
            )

    async def list_devices(self) -> list[DeviceInfo]:
        """List all registered Find Hub devices.

        Returns:
            List of Device objects.
        """

        async def inner() -> list[DeviceInfo]:
            self._check_available()
            self._check_auth()

            devices = await asyncio.to_thread(list_devices)
            log.info("devices_listed", count=len(devices))
            return devices

        return await self._devices_cache.get_or_set(inner)

    async def get_device_location(self, device: DeviceInfo) -> DeviceLocation | None:
        """Request and retrieve the current location for a device.

        Args:
            device: The device object for which to get location information.

        Returns:
            DeviceLocation if a location was obtained, None otherwise.
        """
        self._check_available()
        self._check_auth()

        try:
            output = await asyncio.to_thread(
                get_location_data_for_device, device.id, device.name, timeout=30
            )
            return parse_location_output(output, device.id)

        except LocationRequestTimeout:
            log.warning("location_request_timeout", device=device.name)
            return None
        except LocationRequestError:
            log.exception("location_request_failed", device=device.name)
            return None

    async def get_all_locations(
        self, device_filter: list[str] | None = None
    ) -> list[DeviceLocation]:
        """Get current locations for all (or filtered) devices.

        Args:
            device_filter: Optional list of device names to track.
                          Empty list or None means track all.

        Returns:
            List of DeviceLocation objects for devices that returned data.
        """
        devices = await self.list_devices()

        if device_filter:
            filter_lower = {n.lower() for n in device_filter}
            devices = [d for d in devices if d.name.lower() in filter_lower]

        locations = []
        for device in devices:
            loc = await self.get_device_location(device)
            if loc:
                locations.append(loc)

        return locations

    async def authenticate(self) -> None:
        """Run the one-time authentication flow (requires Chrome)."""
        self._check_available()
        await asyncio.to_thread(self._authenticate_sync)

    def _authenticate_sync(self) -> None:
        """Synchronous auth flow.

        Triggers the full GoogleFindMyTools chain:
          1. Chrome OAuth login → oauth_token
          2. gpsoauth exchange → AAS token (saved to GoogleFindMyTools/Auth/secrets.json)
          3. FCM registration (cached in same file)
        Then copies the resulting secrets.json into the project's Auth/ directory.
        """
        import shutil

        from Auth.aas_token_retrieval import get_aas_token
        from Auth.token_cache import _get_secrets_file

        # Trigger the full auth chain (Chrome → AAS token → saved to GFMT's Auth/)
        get_aas_token()

        # Copy secrets from GoogleFindMyTools/Auth/secrets.json to project Auth/
        gfmt_secrets = Path(_get_secrets_file())
        dest = self.auth_dir / "secrets.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(gfmt_secrets, dest)

        log.info("authentication_complete", secrets_path=str(dest))
