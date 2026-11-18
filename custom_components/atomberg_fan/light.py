"""The fan's LED."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
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
    async_add_entities([AtombergLed(entry.runtime_data)])


class AtombergLed(AtombergFanEntity, LightEntity):
    """The LED: on or off."""

    _key = "led"
    _attr_translation_key = "led"
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def is_on(self) -> bool | None:
        return None if self.fan_state is None else self.fan_state.led

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send(self.coordinator.fan.set_led(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send(self.coordinator.fan.set_led(False))
