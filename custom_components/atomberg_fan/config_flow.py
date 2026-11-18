"""Config flow: add a fan found over Bluetooth, picked from a list, or by its address.

Each way leads to the same menu: blink the fan's LEDs to find it, or set it
up to connect when needed or to stay connected.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from bleak.exc import BleakError
import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
    async_last_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from .aioatombergfan import AtombergError, AtombergFan, parse_advert_name
from .aioatombergfan.const import NAME_PREFIX
from .const import CONF_DEVICE_ID, CONF_PERSISTENT, CONF_SERIES, DOMAIN, model_name

_LOGGER = logging.getLogger(__name__)

MANUAL = "manual"
_MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")
# A menu can't show errors: the menu shows them as a note.
_NOTES = {
    "cannot_connect": "Couldn't connect. Move the fan's Bluetooth adapter or proxy closer and try again.",
    "no_reply": "The fan connected but didn't report its state.",
    "unknown": "Unexpected error.",
    "identify_failed": "Couldn't blink its LEDs: the fan didn't respond.",
}


def _label(info: BluetoothServiceInfoBleak) -> str:
    """"Renesa (CD-26)": the model with the end of the address."""
    parsed = parse_advert_name(info.name)
    model = model_name(parsed[1] if parsed else None)
    return f"{model} ({info.address[-5:].replace(':', '-')})"


class AtombergFanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add one fan per entry."""

    VERSION = 1

    def __init__(self) -> None:
        self._info: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}
        self._identify_task: asyncio.Task[str | None] | None = None
        self._note = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AtombergFanOptionsFlow:
        return AtombergFanOptionsFlow()

    # --- Ways in

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """A fan Home Assistant heard advertising."""
        if parse_advert_name(discovery_info.name) is None:
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._info = discovery_info
        self.context["title_placeholders"] = {"name": _label(discovery_info)}
        self._set_confirm_only()
        return await self.async_step_confirm()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a fan in range, or enter an address."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            if address == MANUAL:
                return await self.async_step_manual()
            return await self._async_chosen(self._discovered[address])

        configured = self._async_current_ids(include_ignore=False)
        self._discovered = {
            info.address: info
            for info in async_discovered_service_info(self.hass, connectable=True)
            if (info.name or "").startswith(NAME_PREFIX)
            and info.address not in configured
        }
        if not self._discovered:
            return await self.async_step_manual()
        choices = {address: _label(info) for address, info in self._discovered.items()}
        choices[MANUAL] = "Enter an address"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(choices)}),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter the fan's Bluetooth address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper().replace("-", ":")
            if not _MAC_RE.match(address):
                errors[CONF_ADDRESS] = "invalid_address"
            elif (info := async_last_service_info(self.hass, address, connectable=True)) is None:
                errors["base"] = "not_found"
            else:
                return await self._async_chosen(info)
        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): str}),
            errors=errors,
        )

    async def _async_chosen(self, info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        await self.async_set_unique_id(info.address, raise_on_progress=False)
        self._abort_if_unique_id_configured()
        self._info = info
        return await self.async_step_confirm()

    # --- The menu

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Blink its LEDs, or set it up to connect when needed or stay connected."""
        assert self._info is not None
        note, self._note = self._note, ""
        return self.async_show_menu(
            step_id="confirm",
            menu_options=["identify", "setup_on_demand", "setup_persistent"],
            description_placeholders={
                "name": _label(self._info),
                "address": self._info.address,
                "note": f"\n\n**{note}**" if note else "",
            },
        )

    async def async_step_setup_on_demand(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_setup(persistent=False)

    async def async_step_setup_persistent(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_setup(persistent=True)

    async def _async_setup(self, *, persistent: bool) -> ConfigFlowResult:
        """Check the fan responds, then add it."""
        assert self._info is not None
        fan_or_error = await self._async_check(self._info)
        if isinstance(fan_or_error, str):
            self._note = _NOTES.get(fan_or_error, _NOTES["unknown"])
            return await self.async_step_confirm()
        parsed = parse_advert_name(self._info.name)
        return self.async_create_entry(
            title=model_name(fan_or_error.series),
            data={
                CONF_ADDRESS: self._info.address,
                CONF_SERIES: fan_or_error.series,
                CONF_DEVICE_ID: parsed[0] if parsed else None,
            },
            options={CONF_PERSISTENT: persistent},
        )

    async def _async_check(self, info: BluetoothServiceInfoBleak) -> AtombergFan | str:
        """Read the fan once; return it, or an error key."""
        parsed = parse_advert_name(info.name)
        fan = AtombergFan(info.device, parsed[1] if parsed else None)
        try:
            state = await fan.async_refresh(user=True)
        except (AtombergError, BleakError, TimeoutError):
            _LOGGER.debug("Could not read %s", info.address, exc_info=True)
            return "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error reading %s", info.address)
            return "unknown"
        finally:
            await fan.async_disconnect()
        if state is None:
            return "no_reply"
        return fan

    # --- Identify: blink the LEDs, to find which fan this is

    async def async_step_identify(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._info is not None
        if self._identify_task is None:
            self._identify_task = self.hass.async_create_task(self._async_identify(self._info))
        if self._identify_task.done():
            return self.async_show_progress_done(next_step_id="identify_done")
        return self.async_show_progress(
            step_id="identify",
            progress_action="identifying",
            progress_task=self._identify_task,
        )

    async def async_step_identify_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Back to the menu."""
        assert self._identify_task is not None
        error = self._identify_task.result()
        self._identify_task = None
        self._note = _NOTES[error] if error else ""
        return await self.async_step_confirm()

    async def _async_identify(self, info: BluetoothServiceInfoBleak) -> str | None:
        parsed = parse_advert_name(info.name)
        fan = AtombergFan(info.device, parsed[1] if parsed else None)
        try:
            await fan.identify()
        except Exception as err:  # noqa: BLE001 - unreachable or no answer
            _LOGGER.debug("Couldn't blink %s: %s", info.address, err)
            return "identify_failed"
        finally:
            await fan.async_disconnect()
        return None

    @callback
    def async_remove(self) -> None:
        """Stop a blink if the dialog is closed while it runs."""
        if self._identify_task is not None:
            self._identify_task.cancel()


class AtombergFanOptionsFlow(OptionsFlow):
    """Stay connected, or connect when needed."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PERSISTENT,
                        default=self.config_entry.options.get(CONF_PERSISTENT, False),
                    ): bool
                }
            ),
        )
