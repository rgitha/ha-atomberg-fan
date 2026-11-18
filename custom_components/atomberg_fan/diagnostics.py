"""Diagnostics download: what the integration knows about one fan."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from . import AtombergFanConfigEntry
from .const import CONF_DEVICE_ID

TO_REDACT = {CONF_ADDRESS, CONF_DEVICE_ID, "title"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AtombergFanConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    fan = coordinator.fan
    info = bluetooth.async_last_service_info(hass, fan.address, connectable=True)
    return {
        "entry": async_redact_data(
            {"title": entry.title, "data": dict(entry.data), "options": dict(entry.options)},
            TO_REDACT,
        ),
        "state": None if fan.state is None else asdict(fan.state),
        "state_raw0": None if fan.state is None else f"0x{fan.state.raw0:02x}",
        "persistent": fan.persistent,
        "connected": fan.connected,
        "heard": coordinator.available,
        "last_update": coordinator.last_update.isoformat() if coordinator.last_update else None,
        "advertisement": None if info is None else {
            "rssi": info.rssi,
            "source": info.source,
        },
    }
