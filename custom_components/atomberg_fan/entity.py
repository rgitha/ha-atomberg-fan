"""Base entity and command handling for Atomberg fans."""
from __future__ import annotations

from collections.abc import Awaitable
import logging

from .aioatombergfan import AtombergError, DeviceBusy, FanState
from bleak.exc import BleakError

from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo

from .const import CONF_SERIES, DOMAIN, model_name
from .coordinator import AtombergFanCoordinator

_LOGGER = logging.getLogger(__name__)


class AtombergFanEntity(PassiveBluetoothCoordinatorEntity[AtombergFanCoordinator]):
    """An entity of one fan. Available once the fan is heard and read."""

    _attr_has_entity_name = True
    _key: str

    def __init__(self, coordinator: AtombergFanCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        address: str = entry.data[CONF_ADDRESS]
        series: str | None = entry.data.get(CONF_SERIES)
        self._attr_unique_id = f"{address}_{self._key}"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            manufacturer="Atomberg",
            model=model_name(series),
            model_id=series,
            name=entry.title,
        )

    @property
    def fan_state(self) -> FanState | None:
        return self.coordinator.state

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.state is not None

    async def _send(self, command: Awaitable[object], *, read_back: bool = True) -> None:
        """Run a command; then read the state back, as the fan's own report
        can be missed. Failures show as a translated error (a toast)."""
        try:
            await command
        except DeviceBusy as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="device_busy"
            ) from err
        except (AtombergError, BleakError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="cannot_connect"
            ) from err
        if not read_back:
            return
        try:
            await self.coordinator.fan.async_refresh()
        except (AtombergError, BleakError, TimeoutError) as err:
            _LOGGER.debug("Read-back after a command failed: %s", err)
