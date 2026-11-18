"""The off-timer."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AtombergFanConfigEntry
from .entity import AtombergFanEntity

PARALLEL_UPDATES = 1

# Option -> hours.
TIMER_OPTIONS = {"off": 0, "1h": 1, "2h": 2, "3h": 3, "6h": 6}
_HOURS_TO_OPTION = {hours: option for option, hours in TIMER_OPTIONS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AtombergFanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([AtombergTimer(entry.runtime_data)])


class AtombergTimer(AtombergFanEntity, SelectEntity):
    """Turns the fan off after 1, 2, 3 or 6 hours."""

    _key = "timer"
    _attr_translation_key = "timer"
    _attr_options = list(TIMER_OPTIONS)

    @property
    def current_option(self) -> str | None:
        if self.fan_state is None:
            return None
        return _HOURS_TO_OPTION.get(self.fan_state.timer_hours)

    async def async_select_option(self, option: str) -> None:
        await self._send(self.coordinator.fan.set_timer_hours(TIMER_OPTIONS[option]))
