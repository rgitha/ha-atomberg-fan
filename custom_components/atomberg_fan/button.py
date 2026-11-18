"""Buttons: Identify (blink the speed LEDs) and Update status (read the fan now)."""
from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
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
    coordinator = entry.runtime_data
    async_add_entities([AtombergIdentify(coordinator), AtombergUpdateStatus(coordinator)])


class AtombergIdentify(AtombergFanEntity, ButtonEntity):
    """Blink the speed LEDs a few times, then leave them as they were
    (HA's standard identify button: the type sets its icon and name)."""

    _key = "identify"
    _attr_device_class = ButtonDeviceClass.IDENTIFY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        await self._send(self.coordinator.fan.identify())


class AtombergUpdateStatus(AtombergFanEntity, ButtonEntity):
    """Read the fan now."""

    _key = "update_status"
    _attr_translation_key = "update_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        await self._send(self.coordinator.fan.async_refresh(user=True), read_back=False)
