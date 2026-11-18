"""Diagnostic binary sensors: Wi-Fi configured (best guess) and the Bluetooth link."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AtombergFanConfigEntry
from .entity import AtombergFanEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AtombergFanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([AtombergWifiConfigured(coordinator), AtombergLink(coordinator)])


class AtombergWifiConfigured(AtombergFanEntity, BinarySensorEntity):
    """Field 17 of the state string: went from 0 to 1 after Wi-Fi credentials were written."""

    _key = "wifi_configured"
    _attr_translation_key = "wifi_configured"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        details = self.coordinator.fan.details
        return super().available and details is not None and details.wifi_configured is not None

    @property
    def is_on(self) -> bool | None:
        details = self.coordinator.fan.details
        return None if details is None else details.wifi_configured


class AtombergLink(AtombergFanEntity, BinarySensorEntity):
    """Whether the Bluetooth link is open: Active or Idle."""

    _key = "connection_link"
    _attr_translation_key = "connection_link"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.fan.connected
