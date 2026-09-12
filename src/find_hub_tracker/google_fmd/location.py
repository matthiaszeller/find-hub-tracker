"""

"""
import contextlib
import io
import threading
from contextlib import redirect_stdout
from datetime import datetime, UTC

import structlog

from GoogleFindMyTools.Auth.fcm_receiver import FcmReceiver
from GoogleFindMyTools.NovaApi.ExecuteAction.LocateTracker.decrypt_locations import decrypt_location_response_locations
from GoogleFindMyTools.NovaApi.ExecuteAction.LocateTracker.location_request import create_location_request
from GoogleFindMyTools.NovaApi.nova_request import nova_request
from GoogleFindMyTools.NovaApi.scopes import NOVA_ACTION_API_SCOPE
from GoogleFindMyTools.NovaApi.util import generate_random_uuid
from GoogleFindMyTools.ProtoDecoders.decoder import parse_device_update_protobuf

from find_hub_tracker.models import DeviceLocation
from find_hub_tracker.utils import utc_now


class LocationRequestError(Exception):
    """Nova API rejected the request outright."""


class LocationRequestTimeout(LocationRequestError):
    """Request was accepted but no FCM response arrived in time."""


log = structlog.get_logger()

def get_location_data_for_device(canonic_device_id, name, timeout=30) -> str:
    """
    Adapter around GoogleFindMyTools.NovaApi.ExecuteAction.LocateTracker
                    .location_request.get_location_data_for_device

    The upstream function is blocking and manages its own event loop
    internally (via FcmReceiver), so it cannot be awaited or called directly
    from within a running asyncio event loop — doing so raises
    "RuntimeError: Cannot run the event loop while another loop is running".
    Call it from a plain sync context, or via asyncio.to_thread(...) if you
    need to call it from async code.

    The upstream function also communicates results and errors purely via
    stdout (printing "Latitude: ...", "Error 500", etc.) rather than return
    values or exceptions, and can hang forever if the Nova API request fails,
    since it busy-waits on `while result is None: time.sleep(0.1)` with no
    timeout and never checks the Nova API response for failure.

    This adapter fixes those issues:
        - Uses threading.Event to wait for the FCM response instead of
          busy-waiting on a sleep loop.
        - Checks the Nova API response and captures any error output instead
          of silently waiting forever on a rejected request.
        - Raises LocationRequestError if Nova API rejects the request, and
          LocationRequestTimeout if no FCM response arrives within `timeout`
          seconds, instead of hanging indefinitely or failing silently.
        - Captures the stdout emitted by the upstream decrypt step and
          returns it as a string, since the upstream code only prints the
          decrypted location fields rather than returning them.

    Args:
        canonic_device_id: The device's canonical ID from list_devices().
        name: Human-readable device name (used for logging/error messages).
        timeout: Seconds to wait for an FCM location response before raising
            LocationRequestTimeout. Defaults to 30.

    Returns:
        The raw stdout produced by decrypt_location_response_locations,
        containing lines such as "Latitude: ...", "Longitude: ...",
        "Accuracy: ...", etc. Parse this with a helper such as
        _parse_location_output() to get a structured result.

    Raises:
        LocationRequestError: Nova API rejected the request outright
            (e.g. a 500 Internal Server Error).
        LocationRequestTimeout: The request was accepted but no FCM
            response arrived within `timeout` seconds.
    """
    request_uuid = generate_random_uuid()
    result = None
    done = threading.Event()

    def handle_location_response(response):
        nonlocal result
        device_update = parse_device_update_protobuf(response)
        if device_update.fcmMetadata.requestUuid == request_uuid:
            result = device_update
            done.set()

    fcm_token = FcmReceiver().register_for_location_updates(handle_location_response)
    hex_payload = create_location_request(canonic_device_id, fcm_token, request_uuid)

    captured = io.StringIO()
    with redirect_stdout(captured):
        response = nova_request(NOVA_ACTION_API_SCOPE, hex_payload)

    error_output = captured.getvalue().strip()
    if error_output or response is None:
        raise LocationRequestError(f"Nova API rejected the request: {error_output or 'No response'}")

    if not done.wait(timeout=timeout):
        raise LocationRequestTimeout(f"No location response for {name} within {timeout}s")

    captured = io.StringIO()
    with redirect_stdout(captured):
        decrypt_location_response_locations(result)

    output = captured.getvalue()
    return output


def parse_location_output(
    output: str, canonic_id: str
) -> DeviceLocation | None:
    """Parse the console output from GoogleFindMyTools into a DeviceLocation.

    The library prints lines like:
        Latitude: 47.1234567
        Longitude: -122.1234567
        Altitude: 50
        Time: 1711234567
        Accuracy: 25.0
        Status: LAST_KNOWN(1)
        Is own report: True
    """
    lat = lng = accuracy = None
    timestamp = None

    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Latitude:"):
            with contextlib.suppress(ValueError):
                lat = float(line.split(":", 1)[1].strip())
        elif line.startswith("Longitude:"):
            with contextlib.suppress(ValueError):
                lng = float(line.split(":", 1)[1].strip())
        elif line.startswith("Time:"):
            try:
                unix_ts = int(line.split(":", 1)[1].strip())
                timestamp = datetime.fromtimestamp(unix_ts, tz=UTC)
            except ValueError:
                pass
        elif line.startswith("Accuracy:"):
            with contextlib.suppress(ValueError):
                accuracy = float(line.split(":", 1)[1].strip())

    if lat is None or lng is None:
        log.warning("location_parse_failed", device=canonic_id, output=output[:200])
        return None

    now = utc_now()
    return DeviceLocation(
        device_id=canonic_id,
        latitude=lat,
        longitude=lng,
        accuracy_meters=accuracy,
        timestamp=timestamp or now,
        polled_at=now,
        battery_percent=None,
        is_charging=None,
    )
