"""Home Assistant test setup, and a fake fan that acts like the real one."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.atomberg_fan.aioatombergfan import device as devmod
from custom_components.atomberg_fan.aioatombergfan.const import CMD_CHAR

from custom_components.atomberg_fan.const import DOMAIN

ADDRESS = "34:CD:B0:C8:CD:26"
NAME = "Atomberg_R1_34cdb0c8cd24"
TIMER_VALUE_TO_HOURS = {0: 0, 1: 1, 2: 2, 3: 3, 4: 6}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def no_deps():
    # Skip setting up the bluetooth_adapters dependency in the test hass.
    with patch("homeassistant.setup.async_process_deps_reqs", AsyncMock()), patch(
        "homeassistant.config_entries.async_process_deps_reqs", AsyncMock(), create=True
    ):
        yield


class FakeClient:
    """Stands in for BleakClient: applies commands like the R1 does, and
    reports the new state as a notification."""

    def __init__(self) -> None:
        self.is_connected = False
        self.writes: list[dict] = []
        self.flags = 0x04  # off, speed 4
        self.timer = 0
        self.notify = None
        self.fail_connect = False
        self.on_disconnect = None
        self.string_reads = 0
        self.connects = 0

    async def disconnect(self) -> None:
        self.is_connected = False
        if self.on_disconnect:
            self.on_disconnect(self)

    async def start_notify(self, _uuid, handler) -> None:
        self.notify = handler

    def state_bytes(self) -> bytearray:
        return bytearray([self.flags, 0, self.timer, 0])

    async def write_gatt_char(self, _uuid, data, response=True) -> None:
        cmd = json.loads(bytes(data))
        self.writes.append(cmd)
        assert len(cmd) == 1, "the fan ignores a command with two settings"
        ((key, value),) = cmd.items()
        if key == "speed":
            self.flags = (self.flags & ~0x47) | value | 0x10 | (0x40 if value == 6 else 0)
        elif key == "timer":
            self.timer = TIMER_VALUE_TO_HOURS[value]
        else:
            bit = {"power": 0x10, "led": 0x20, "sleep": 0x80}[key]
            self.flags = (self.flags | bit) if value else (self.flags & ~bit)
        if self.notify:
            self.notify(None, self.state_bytes())

    async def read_gatt_char(self, uuid):
        if uuid == CMD_CHAR:
            return self.state_bytes()
        self.string_reads += 1
        return (
            f"{self.flags},1,Z,10,158.80,159,240,R1,565,4,725,11541641,156802869,27979229,0,"
            "0.93,24.00,1,77142859,0,0,0,323,0,321,END"
        ).encode()


@pytest.fixture
def client(monkeypatch) -> FakeClient:
    fake = FakeClient()

    async def _connect(_dev, on_disconnect):
        fake.connects += 1
        if fake.fail_connect:
            raise devmod.BleakError("out of range")
        fake.on_disconnect = on_disconnect
        fake.is_connected = True
        return fake

    monkeypatch.setattr(devmod, "_raw_connect", _connect)
    monkeypatch.setattr(devmod, "CONNECT_SETTLE", 0.0)
    monkeypatch.setattr(devmod, "IDLE_DISCONNECT", 0.0)
    monkeypatch.setattr(devmod, "IDENTIFY_INTERVAL", 0.0)
    return fake


def service_info(address: str = ADDRESS, name: str = NAME, rssi: int = -60):
    return SimpleNamespace(
        address=address,
        name=name,
        rssi=rssi,
        source="local",
        time=time.monotonic(),
        device=SimpleNamespace(address=address, name=name, details=None),
    )


def make_entry(hass, options=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bedroom",
        unique_id=ADDRESS,
        data={"address": ADDRESS, "series": "R1", "device_id": "34cdb0c8cd24"},
        options=options or {},
    )
    entry.add_to_hass(hass)
    return entry


BT = "homeassistant.components.bluetooth"
BT_COORD = f"{BT}.update_coordinator"


@pytest.fixture
def adverts():
    """The coordinator's advertisement callbacks, per setup."""
    return []


@pytest.fixture
def bluetooth(adverts):
    info = service_info()
    patches = [
        patch(f"{BT}.async_ble_device_from_address", return_value=info.device),
        patch(f"{BT}.async_last_service_info", return_value=info),
        patch(f"{BT}.async_rediscover_address"),
        patch(f"{BT}.async_scanner_by_source", return_value=SimpleNamespace(name="esp32-proxy")),
        patch(f"{BT_COORD}.async_address_present", return_value=True),
        patch(
            f"{BT_COORD}.async_register_callback",
            side_effect=lambda hass, cb, matcher, mode: adverts.append(cb) or (lambda: None),
        ),
        patch(f"{BT_COORD}.async_track_unavailable", return_value=lambda: None),
    ]
    for p in patches:
        p.start()
    yield info
    for p in patches:
        p.stop()


@pytest.fixture
def clock():
    """The monotonic clock the coordinator and its base class use."""
    now = [1000.0]
    with patch(
        "custom_components.atomberg_fan.coordinator.monotonic_time_coarse", lambda: now[0]
    ), patch(
        "homeassistant.components.bluetooth.active_update_coordinator.monotonic_time_coarse",
        lambda: now[0],
    ), patch(
        "custom_components.atomberg_fan.aioatombergfan.device.monotonic", lambda: now[0]
    ):
        yield now
