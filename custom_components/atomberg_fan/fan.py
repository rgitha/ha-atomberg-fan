"""The fan: power, speeds 1-5 and Boost."""
from __future__ import annotations

import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from . import AtombergFanConfigEntry
from .entity import AtombergFanEntity

PARALLEL_UPDATES = 1

SPEED_RANGE = (1, 5)
BOOST_SPEED = 6
PRESET_BOOST = "boost"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AtombergFanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([AtombergFan(entry.runtime_data)])


class AtombergFan(AtombergFanEntity, FanEntity):
    """Power, speed 1-5 and the Boost preset (the fan's speed 6)."""

    _key = "fan"
    _attr_name = None
    _attr_translation_key = "fan"
    _attr_speed_count = SPEED_RANGE[1]
    _attr_preset_modes = [PRESET_BOOST]
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )

    @property
    def is_on(self) -> bool | None:
        return None if self.fan_state is None else self.fan_state.power

    @property
    def percentage(self) -> int | None:
        st = self.fan_state
        if st is None:
            return None
        if not st.power:
            return 0
        if st.speed >= BOOST_SPEED:
            return 100
        return ranged_value_to_percentage(SPEED_RANGE, st.speed)

    @property
    def preset_mode(self) -> str | None:
        st = self.fan_state
        if st is not None and st.power and st.speed >= BOOST_SPEED:
            return PRESET_BOOST
        return None

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self.async_turn_off()
            return
        speed = math.ceil(percentage_to_ranged_value(SPEED_RANGE, percentage))
        await self._send(self.coordinator.fan.set_speed(speed))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._send(self.coordinator.fan.set_speed(BOOST_SPEED))

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        elif percentage is not None:
            await self.async_set_percentage(percentage)
        else:
            await self._send(self.coordinator.fan.set_power(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send(self.coordinator.fan.set_power(False))
