"""When to read the fan, and its entities' updates.

The fan is read about once a minute while it is in range: every
``CHECK_INTERVAL`` seconds, a read is started when the last successful read
(from any source) and the last background attempt are older than
``STALE_AFTER``. Home Assistant passes on an advertisement only when its
contents change, and the fan's never do (just its name), so a timer is
needed; an advertisement that does come through (the fan heard again after a
gap) also starts a read when one is due. A failed read is retried a minute
later.

Changes the fan reports while the link is open (commands, the remote) update
the entities straight away. With Stay connected, the link stays open, so
every change shows at once; the fan is still read once a minute, for its
extra details, and straight away when the link drops after a good read.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from bluetooth_data_tools import monotonic_time_coarse

from .aioatombergfan import AtombergFan, FanState

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.core import CALLBACK_TYPE, CoreState, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import CHECK_INTERVAL, STALE_AFTER

if TYPE_CHECKING:
    from . import AtombergFanConfigEntry

_LOGGER = logging.getLogger(__name__)


class AtombergFanCoordinator(ActiveBluetoothDataUpdateCoordinator[None]):
    """Reads one fan when due, and tells its entities of changes."""

    def __init__(
        self, hass: HomeAssistant, entry: AtombergFanConfigEntry, fan: AtombergFan
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            address=fan.address,
            mode=bluetooth.BluetoothScanningMode.PASSIVE,
            needs_poll_method=self._needs_poll,
            poll_method=self._poll,
            connectable=True,
        )
        self.config_entry = entry
        self.fan = fan
        self.last_update: datetime | None = None
        self._unsubs: list[CALLBACK_TYPE] = []
        self._stopped = False

    @property
    def state(self) -> FanState | None:
        return self.fan.state

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Follow advertisements, the fan's own reports, and the read timer."""
        self._unsubs = [
            super().async_start(),
            self.fan.add_callback(self._on_state),
            self.fan.add_link_callback(self._on_link),
            async_track_time_interval(
                self.hass, self._async_check, timedelta(seconds=CHECK_INTERVAL)
            ),
        ]
        return self.async_stop_reads

    @callback
    def async_stop_reads(self) -> None:
        """Stop reading the fan (before unloading). Safe to call twice."""
        self._stopped = True
        unsubs, self._unsubs = self._unsubs, []
        for unsub in unsubs:
            unsub()
        self._debounced_poll.async_cancel()

    @callback
    def _on_state(self, _state: FanState) -> None:
        self.last_update = dt_util.utcnow()
        self.async_update_listeners()

    @callback
    def _on_link(self, up: bool) -> None:
        self.async_update_listeners()
        if not up:
            self._async_check()  # Stay connected: reconnect after a drop

    def _is_due(self) -> bool:
        if self._stopped or self.hass.state is not CoreState.running:
            return False
        if not self._available:  # not heard: out of range
            return False
        if self.fan.persistent and not self.fan.connected and self.last_poll_successful:
            return True  # the link dropped after a good read
        # Due a minute after the last successful read from any source (a
        # background read, Update status, a command's read-back) or the last
        # background attempt, whichever is later: a failed attempt waits a
        # minute, and a recent read pushes the next one back.
        times = [t for t in (self.fan.last_read, self._last_poll) if t is not None]
        if not times:
            return True
        return monotonic_time_coarse() - max(times) >= STALE_AFTER

    @callback
    def _async_check(self, _now: datetime | None = None) -> None:
        """Start a read if one is due, through the latest adapter or proxy."""
        if not self._is_due():
            return
        info = bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
        if info is None:
            return
        self.fan.set_ble_device(info.device)
        self._last_service_info = info
        _LOGGER.debug("%s: a read is due", self.address)
        self._debounced_poll.async_schedule_call()

    @callback
    def _async_handle_bluetooth_event(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        # Not the base class's: it writes every entity on every advertisement
        # (several a second). Entities follow the fan's state reports, and
        # being heard again after a gap.
        self.fan.set_ble_device(service_info.device)  # the adapter or proxy that hears it now
        self._last_service_info = service_info
        if not self._available:
            _LOGGER.info("%s is heard again; its entities are available", self.address)
            self._available = True
            self.async_update_listeners()
        if self.needs_poll(service_info):
            self._debounced_poll.async_schedule_call()

    @callback
    def _async_handle_unavailable(
        self, service_info: bluetooth.BluetoothServiceInfoBleak
    ) -> None:
        _LOGGER.info("%s is no longer heard; its entities are unavailable", self.address)
        super()._async_handle_unavailable(service_info)

    def _needs_poll(
        self,
        _service_info: bluetooth.BluetoothServiceInfoBleak,
        _seconds_since_last_poll: float | None,
    ) -> bool:
        return self._is_due()

    async def _poll(self, _service_info: bluetooth.BluetoothServiceInfoBleak) -> None:
        # Failures are logged by the base class, and retried a minute later.
        await self.fan.async_refresh()
