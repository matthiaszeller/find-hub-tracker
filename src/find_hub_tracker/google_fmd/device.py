from dataclasses import dataclass

from GoogleFindMyTools.NovaApi.ListDevices.nbe_list_devices import request_device_list
from GoogleFindMyTools.ProtoDecoders.decoder import get_canonic_ids, parse_device_list_protobuf


@dataclass
class Device:
    canonic_id: str
    name: str


def list_devices() -> list[Device]:
    """Synchronous device listing (runs in thread)."""

    hex_result = request_device_list()
    device_list = parse_device_list_protobuf(hex_result)
    return [Device(canonic_id=canonic_id, name=name) for name, canonic_id in get_canonic_ids(device_list)]
