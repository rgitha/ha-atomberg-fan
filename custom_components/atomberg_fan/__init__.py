"""Local Bluetooth control of Atomberg fans."""
from __future__ import annotations

from bluetooth_data_tools import monotonic_time_coarse

from .aioatombergfan import AtombergFan

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_PERSISTENT, CONF_SERIES, DOMAIN, HEARD_RECENTLY
from .coordinator import AtombergFanCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.FAN,
    Platform.LIGHT,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type AtombergFanConfigEntry = ConfigEntry[AtombergFanCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: AtombergFanConfigEntry) -> bool:
    """Set up a fan from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="not_found",
            translation_placeholders={"address": address},
        )

    def heard_recently() -> str | None:
        """The adapter or proxy that heard the fan recently, if any: a failed
        connection attempt then counts towards the "can't connect" warning."""
        info = bluetooth.async_last_service_info(hass, address, connectable=True)
        if info is None or monotonic_time_coarse() - info.time > HEARD_RECENTLY:
            return None
        scanner = bluetooth.async_scanner_by_source(hass, info.source)
        return getattr(scanner, "name", None) or info.source

    fan = AtombergFan(
        ble_device,
        entry.data.get(CONF_SERIES),
        persistent=entry.options.get(CONF_PERSISTENT, False),
        heard_recently=heard_recently,
    )
    coordinator = AtombergFanCoordinator(hass, entry, fan)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    # Reads start with the fan's next advertisement.
    entry.async_on_unload(coordinator.async_start())
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AtombergFanConfigEntry) -> bool:
    """Unload a config entry and drop the link."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = entry.runtime_data
        coordinator.async_stop_reads()  # no reconnect when the link drops
        await coordinator.fan.async_shutdown()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Offer the fan again straight away after it is deleted."""
    bluetooth.async_rediscover_address(hass, entry.data[CONF_ADDRESS])


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options changed (always-connected link): reload."""
    await hass.config_entries.async_reload(entry.entry_id)
