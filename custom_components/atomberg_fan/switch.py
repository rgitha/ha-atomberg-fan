"""Sleep mode."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AtombergFanConfigEntry
from .entity import AtombergFanEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AtombergFanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([AtombergSleep(entry.runtime_data)])


class AtombergSleep(AtombergFanEntity, SwitchEntity):
    """Sleep mode on or off."""

    _key = "sleep"
    _attr_translation_key = "sleep"

    @property
    def is_on(self) -> bool | None:
        return None if self.fan_state is None else self.fan_state.sleep

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send(self.coordinator.fan.set_sleep(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send(self.coordinator.fan.set_sleep(False))
