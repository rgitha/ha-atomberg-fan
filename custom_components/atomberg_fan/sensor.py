"""Diagnostic sensors: signal strength, when the fan last reported, and
the extra fields of its state string (best-guess names, not yet confirmed)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components import bluetooth
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    REVOLUTIONS_PER_MINUTE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AtombergFanConfigEntry
from .aioatombergfan import FanDetails
from .coordinator import AtombergFanCoordinator
from .entity import AtombergFanEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class DetailDescription(SensorEntityDescription):
    value: Callable[[FanDetails], float | int | None]


DETAILS: tuple[DetailDescription, ...] = (
    DetailDescription(
        key="motor_speed",
        translation_key="motor_speed",
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: d.rpm,
    ),
    DetailDescription(
        key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: d.voltage,
    ),
    DetailDescription(
        key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: d.current,
    ),
    DetailDescription(
        key="board_temperature",
        translation_key="board_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: d.board_temp,
    ),
    DetailDescription(
        key="runtime",
        translation_key="runtime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=0,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value=lambda d: d.runtime_s,
    ),
    DetailDescription(
        key="restarts",
        translation_key="restarts",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value=lambda d: d.restarts,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AtombergFanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            AtombergSignal(coordinator),
            AtombergUpdatedLast(coordinator),
            *(AtombergDetail(coordinator, description) for description in DETAILS),
        ]
    )


class AtombergSignal(AtombergFanEntity, SensorEntity):
    """Signal strength of the fan's last advertisement."""

    _key = "signal_strength"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return self.coordinator.available

    @property
    def native_value(self) -> int | None:
        info = bluetooth.async_last_service_info(
            self.hass, self.coordinator.address, connectable=True
        )
        return None if info is None else info.rssi


class AtombergUpdatedLast(AtombergFanEntity, SensorEntity):
    """When the fan last reported its state."""

    _key = "updated_last"
    _attr_translation_key = "updated_last"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_update


class AtombergDetail(AtombergFanEntity, SensorEntity):
    """One extra field of the fan's state string."""

    entity_description: DetailDescription
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: AtombergFanCoordinator, description: DetailDescription
    ) -> None:
        self._key = description.key
        self.entity_description = description
        super().__init__(coordinator)

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.fan.details is not None

    @property
    def native_value(self) -> float | int | None:
        details = self.coordinator.fan.details
        return None if details is None else self.entity_description.value(details)
