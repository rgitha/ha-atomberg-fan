"""Scan for Atomberg fans over BLE."""
from __future__ import annotations

from bleak import BleakScanner
from bleak.backends.device import BLEDevice

from .device import parse_advert_name


async def discover(timeout: float = 8.0) -> dict[str, tuple[BLEDevice, str]]:
    """Return {device_id: (BLEDevice, series)} for Atomberg fans in range."""
    found: dict[str, tuple[BLEDevice, str]] = {}
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for _addr, (dev, adv) in devices.items():
        parsed = parse_advert_name(adv.local_name or dev.name)
        if parsed:
            device_id, series = parsed
            found[device_id] = (dev, series)
    return found
