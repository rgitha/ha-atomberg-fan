"""Async BLE client for an Atomberg fan (verified on R1 / Renesa).

Connection model:

* Every exchange runs inside one `_operation`: operations run one at a time,
  each whole, so nothing slips in between a check and the command it decides.
  Re-entrant: the steps of an operation don't queue again.
* Connecting and disconnecting run under one `_connect_lock`, so a connect
  never overlaps a disconnect. The exchange itself also holds it, so the idle
  disconnect can't close the link mid-exchange.
* One connection attempt runs at a time (`CONNECT_ATTEMPTS`), as its own task
  that is never cut short: callers wait on it, shielded, for as long as they
  can, and the connect library's own timeout ends a failing one. A link that
  comes up after everyone stopped waiting is closed.
* Once the link is up, any failure (cancellation included) closes it again,
  so a failed attempt never leaves the fan connected. The same goes for an
  exchange that fails: its link is closed at once, never reused.
* The link is closed `IDLE_DISCONNECT` seconds after the last operation. The
  idle disconnect takes the connect lock and rechecks that no operation
  started meanwhile.
* A user request gets a deadline: it must get its turn and the link within
  `CONNECT_TIMEOUT` of the request, or fail (`DeviceBusy` / `NotConnected`)
  rather than go out late. Background reads wait for the whole attempt, and
  give way to a waiting user request.
* After `STUCK_AFTER` failed attempts in a row while the fan is still heard,
  a warning says the adapter or proxy may need a restart.

Protocol note: the fan has no message number. A command's "ack" is the GATT
write-response; the state notification/read-back that follows is a separate
concern and never fails the command.

`persistent=True` keeps the link open (no idle disconnect) and subscribes to
notifications, so every change (the remote included) arrives at once. Default
is connect-on-demand, which only reads: on an R1, after six connections that
each subscribed, the fan stopped answering the subscription write until it was
power-cycled, as if it never frees a subscription when a link closes.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
from collections.abc import AsyncIterator, Callable
from logging import getLogger
from time import monotonic

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from . import commands
from .const import CMD_CHAR, NAME_PREFIX, STATE_CHAR, WIFI_STATUS, WIFI_STATUS_CHAR
from .exceptions import DeviceBusy, NotConnected
from .state import FanDetails, FanState, decode_details, decode_notification, decode_state_string

_LOGGER = getLogger(__name__)

CONNECT_TIMEOUT = 5.0  # user request: get a turn and the link within this
CONNECT_ATTEMPTS = 1  # attempts per connection; the connect library's timeout ends one
IDLE_DISCONNECT = 5.0  # seconds idle before dropping the link (non-persistent)
CONNECT_SETTLE = 0.5  # pause after connecting before the first exchange
STUCK_AFTER = 3  # failed attempts in a row, while heard, before a warning
IDENTIFY_BLINKS = 3  # identify: LED blinks
IDENTIFY_INTERVAL = 0.6  # identify: seconds per half-blink

# A user request's deadline for getting the link (see _operation).
_link_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "atomberg_link_deadline", default=None
)

try:
    from bleak_retry_connector import establish_connection

    async def _raw_connect(
        dev: BLEDevice, on_disconnect: Callable[[BleakClient], None]
    ) -> BleakClient:
        return await establish_connection(
            BleakClient,
            dev,
            dev.address,
            disconnected_callback=on_disconnect,
            max_attempts=CONNECT_ATTEMPTS,
        )
except ImportError:  # pragma: no cover - standalone fallback

    async def _raw_connect(
        dev: BLEDevice, on_disconnect: Callable[[BleakClient], None]
    ) -> BleakClient:
        client = BleakClient(dev, disconnected_callback=on_disconnect)
        await client.connect()
        return client


def parse_advert_name(name: str | None) -> tuple[str, str] | None:
    """`Atomberg_R1_34cdb0c8cd24` -> (device_id, series)."""
    if not name or not name.startswith(NAME_PREFIX):
        return None
    parts = name.split("_")
    if len(parts) < 3:
        return None
    return parts[2], parts[1]  # device_id, series


StateCallback = Callable[[FanState], None]
LinkCallback = Callable[[bool], None]
# Returns the adapter or proxy that heard the fan recently, or None if it
# hasn't been heard recently (a failed attempt then isn't the proxy's fault).
HeardRecently = Callable[[], str | None]


class AtombergFan:
    """A BLE control session to one fan."""

    def __init__(
        self,
        device: BLEDevice,
        series: str | None = None,
        *,
        persistent: bool = False,
        heard_recently: HeardRecently | None = None,
    ) -> None:
        self._device = device
        self.series = series
        self.persistent = persistent
        self._heard_recently = heard_recently
        self.state: FanState | None = None
        self.details: FanDetails | None = None  # extra state-string fields
        self.last_read: float | None = None  # monotonic time of the last successful read

        self._client: BleakClient | None = None
        self._callbacks: list[StateCallback] = []
        self._link_callbacks: list[LinkCallback] = []
        self._link_up = False
        self._subscribed = False

        # one operation at a time (re-entrant for the owning task)
        self._command_lock = asyncio.Lock()
        self._command_owner: asyncio.Task[object] | None = None
        self._user_waiting = 0  # user requests waiting: background reads give way

        # connecting and disconnecting
        self._connect_lock = asyncio.Lock()
        self._link_task: asyncio.Task[BleakClient] | None = None
        self._link_waiters = 0
        self._link_failures = 0

        # link lifetime
        self._link_holds = 0
        self._disconnect_task: asyncio.Task[None] | None = None

    # ---------------------------------------------------------------- state
    @property
    def address(self) -> str:
        return self._device.address

    def set_ble_device(self, device: BLEDevice) -> None:
        """Use a newer BLEDevice for the next connect, e.g. when another
        adapter or proxy now hears the fan best."""
        self._device = device

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def add_callback(self, cb: StateCallback) -> Callable[[], None]:
        self._callbacks.append(cb)
        return lambda: self._callbacks.remove(cb)

    def add_link_callback(self, cb: LinkCallback) -> Callable[[], None]:
        """Call cb(True) when the link opens and cb(False) when it closes."""
        self._link_callbacks.append(cb)
        return lambda: self._link_callbacks.remove(cb)

    def _set_link(self, up: bool) -> None:
        if up == self._link_up:
            return
        self._link_up = up
        for cb in list(self._link_callbacks):
            try:
                cb(up)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("link callback failed")

    def _emit(self, state: FanState) -> None:
        if state.series is None:
            state.series = self.series
        self.state = state
        for cb in list(self._callbacks):
            try:
                cb(state)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("state callback failed")

    def _on_notify(self, _char: object, data: bytearray) -> None:
        _LOGGER.debug("%s << notify %s", self.address, bytes(data).hex())
        st = decode_notification(bytes(data))
        if st is not None:
            self._emit(st)

    def _on_disconnect(self, client: BleakClient) -> None:
        _LOGGER.debug("%s disconnected", self.address)
        if self._client is client:
            self._client = None
            self._subscribed = False
        self._set_link(False)

    # ------------------------------------------------------------ operation
    @contextlib.asynccontextmanager
    async def _operation(self, purpose: str, *, user: bool) -> AsyncIterator[None]:
        """Run one exchange as a single operation. See module docstring."""
        if self._command_owner is not None and self._command_owner is asyncio.current_task():
            yield  # a step of the operation already in progress
            return
        deadline: float | None = None
        if user:
            deadline = asyncio.get_running_loop().time() + CONNECT_TIMEOUT
            self._user_waiting += 1  # background reads give way
        waiting = user
        try:
            async with self._command_queue(deadline), self._holding_link():
                if waiting:
                    self._user_waiting -= 1
                    waiting = False
                token = _link_deadline.set(deadline)
                try:
                    async with self._connect_lock:
                        await self._open_connection(purpose)
                        try:
                            yield
                        except (Exception, asyncio.CancelledError):
                            # The link may be stuck: never reuse it.
                            _LOGGER.debug("%s: %s failed", self.address, purpose)
                            await self._cleanup_connection()
                            raise
                finally:
                    _link_deadline.reset(token)
        finally:
            if waiting:
                self._user_waiting -= 1

    @contextlib.asynccontextmanager
    async def _command_queue(self, deadline: float | None) -> AsyncIterator[None]:
        """One operation at a time. With a deadline, give up waiting for a
        turn (raise DeviceBusy)."""
        if deadline is None:
            await self._command_lock.acquire()
        else:
            remaining = max(0.0, deadline - asyncio.get_running_loop().time())
            try:
                await asyncio.wait_for(self._command_lock.acquire(), remaining)
            except (TimeoutError, asyncio.TimeoutError) as err:
                raise DeviceBusy(
                    f"{self.address} is busy with another exchange "
                    f"(no turn within {CONNECT_TIMEOUT:g} s)"
                ) from err
        self._command_owner = asyncio.current_task()
        try:
            yield
        finally:
            self._command_owner = None
            self._command_lock.release()

    @contextlib.asynccontextmanager
    async def _holding_link(self) -> AsyncIterator[None]:
        """Keep the link open until the operation ends; then start the idle
        disconnect (unless persistent)."""
        self._link_holds += 1
        self._cancel_idle_disconnect()
        try:
            yield
        finally:
            self._link_holds -= 1
            if self._link_holds == 0 and not self.persistent:
                self._schedule_idle_disconnect()

    # ------------------------------------------------------------ link mgmt
    async def _open_connection(self, purpose: str) -> None:
        """Make sure the link is up and subscribed. Caller holds _connect_lock.

        Once the link is up, any failure closes it before the error goes on,
        so a failed attempt never leaves the fan connected.
        """
        if self.connected:
            _link_deadline.set(None)  # linked in time
            await self._ensure_subscribed()
            return

        deadline = _link_deadline.get()
        wait = None if deadline is None else max(0.0, deadline - asyncio.get_running_loop().time())
        _LOGGER.debug("%s: connecting (%s)", self.address, purpose)
        task = self._link()
        # Wait without the lock: a user request can join a slow attempt that
        # a background read started.
        self._link_waiters += 1
        self._connect_lock.release()
        try:
            client = await asyncio.wait_for(asyncio.shield(task), wait)
        except Exception as err:
            if isinstance(err, (TimeoutError, asyncio.TimeoutError)) and not task.done():
                reason = f"no connection within {CONNECT_TIMEOUT:g} s"  # still trying
            elif isinstance(err, (TimeoutError, asyncio.TimeoutError)):
                reason = "the connection attempt timed out"
            else:
                reason = str(err) or type(err).__name__
            _LOGGER.debug("%s: failed to connect (%s): %s", self.address, purpose, reason)
            raise NotConnected(f"could not connect to {self.address}: {reason}") from err
        finally:
            self._link_waiters -= 1
            await self._connect_lock.acquire()

        _link_deadline.set(None)  # linked in time: later steps aren't held to it
        if self._client is client and client.is_connected:
            await self._ensure_subscribed()  # another waiter took this link
            return
        self._client = client
        self._subscribed = False
        try:
            self._set_link(True)
            await asyncio.sleep(CONNECT_SETTLE)
            if not client.is_connected:
                raise NotConnected(f"{self.address} disconnected right after connecting")
            _LOGGER.debug("%s: connected", self.address)
            await self._ensure_subscribed()
        except BaseException:
            # Cancellation included: never leave the fan connected.
            await self._cleanup_connection()
            raise

    def _link(self) -> asyncio.Task[BleakClient]:
        """The connection attempt in flight, starting one if there is none.
        Callers wait on it (shielded); it is never cancelled here."""
        task = self._link_task
        if task is None or task.done():
            task = asyncio.get_running_loop().create_task(
                _raw_connect(self._device, self._on_disconnect)
            )
            task.add_done_callback(self._on_link_done)
            self._link_task = task
        else:
            _LOGGER.debug("%s: joining the connection attempt in progress", self.address)
        return task

    def _on_link_done(self, task: asyncio.Task[BleakClient]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            _LOGGER.debug("%s: connection attempt ended without a link: %r", self.address, error)
            self._note_link_failure()
            return
        if self._link_failures >= STUCK_AFTER:
            _LOGGER.info("%s can be connected to again", self.address)
        self._link_failures = 0
        # Runs before the waiters resume, so a waiter still counts. If everyone
        # stopped waiting, nobody will use the link: close it.
        if self._link_waiters == 0:
            _LOGGER.debug("%s: connected after everyone stopped waiting; closing", self.address)
            asyncio.get_running_loop().create_task(task.result().disconnect())

    def _note_link_failure(self) -> None:
        """Count failed attempts while the fan is heard; warn once."""
        route = self._heard_recently() if self._heard_recently is not None else "the adapter"
        if route is None:
            self._link_failures = 0
            return
        self._link_failures += 1
        if self._link_failures == STUCK_AFTER:
            _LOGGER.warning(
                "%s is heard but can't be connected to (%d attempts in a row) through %s; "
                "if this continues, restart that adapter or proxy, or power-cycle the fan",
                self.address, self._link_failures, route,
            )

    async def _ensure_subscribed(self) -> None:
        """Subscribe once per link, only when persistent (see module docstring)."""
        client = self._client
        if not self.persistent or self._subscribed or client is None:
            return
        _LOGGER.debug("%s: subscribing to notifications", self.address)
        await client.start_notify(CMD_CHAR, self._on_notify)
        if self._client is not client or not client.is_connected:
            raise NotConnected(f"{self.address} disconnected during notification setup")
        self._subscribed = True

    async def _cleanup_connection(self) -> None:
        """Tear down the link after a failure."""
        client, self._client = self._client, None
        self._subscribed = False
        self._cancel_idle_disconnect()
        self._set_link(False)
        if client is None:
            return
        _LOGGER.debug("%s: closing the link after a failure", self.address)
        try:
            await client.disconnect()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("%s: error closing the link: %s", self.address, err)

    async def _disconnect(self, reason: str) -> None:
        """Close the link. Caller holds _connect_lock."""
        client = self._client
        if client is None or not client.is_connected:
            return
        _LOGGER.debug("%s: disconnecting (%s)", self.address, reason)
        try:
            await client.disconnect()
        except (BleakError, OSError) as err:
            _LOGGER.debug("%s: error disconnecting: %s", self.address, err)
        finally:
            if self._client is client:
                self._client = None
                self._subscribed = False
            self._set_link(False)

    def _cancel_idle_disconnect(self) -> None:
        task, self._disconnect_task = self._disconnect_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    def _schedule_idle_disconnect(self) -> None:
        if self._link_holds:
            return  # the operation holding the link schedules it after
        self._cancel_idle_disconnect()
        self._disconnect_task = asyncio.get_running_loop().create_task(self._idle_disconnect())

    async def _idle_disconnect(self) -> None:
        if not self.connected:
            return
        try:
            await asyncio.sleep(IDLE_DISCONNECT)
            async with self._connect_lock:
                if self._link_holds:
                    return  # an operation started meanwhile
                if self._disconnect_task is asyncio.current_task():
                    self._disconnect_task = None
                await self._disconnect("idle")
        except asyncio.CancelledError:
            return
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("%s: idle disconnect failed: %s", self.address, err)

    async def async_connect(self) -> None:
        """Open the link eagerly and read the state (useful with persistent=True)."""
        await self.async_refresh()

    async def async_disconnect(self) -> None:
        """Close the link now."""
        self._cancel_idle_disconnect()
        async with self._connect_lock:
            await self._disconnect("requested")

    async def async_shutdown(self) -> None:
        """Unloading: stop a connection attempt in flight, then disconnect."""
        task = self._link_task
        if task is not None and not task.done():
            task.cancel()
        await self.async_disconnect()

    async def __aenter__(self) -> "AtombergFan":
        await self.async_connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.async_shutdown()

    # ------------------------------------------------------------- commands
    async def _write(self, payload: bytes) -> None:
        if self._client is None:
            raise NotConnected(f"{self.address} not connected")
        _LOGGER.debug("%s >> %s", self.address, payload.decode(errors="replace"))
        # ack == write-response; state read-back is separate (never fails this)
        await self._client.write_gatt_char(CMD_CHAR, payload, response=True)

    async def _read(self, char: str) -> bytes:
        if self._client is None:
            raise NotConnected(f"{self.address} not connected")
        data = bytes(await self._client.read_gatt_char(char))
        _LOGGER.debug("%s << read %s: %s", self.address, char[:8], data.hex())
        return data

    # Each command is built before its operation starts, so a bad value is
    # refused without touching the link.
    async def set_power(self, on: bool, *, user: bool = True) -> None:
        payload = commands.set_power(on)
        async with self._operation("power", user=user):
            await self._write(payload)

    async def set_speed(self, speed: int, *, user: bool = True) -> None:
        payload = commands.set_speed(speed)  # also powers on if off
        async with self._operation("speed", user=user):
            await self._write(payload)

    async def set_led(self, on: bool, *, user: bool = True) -> None:
        payload = commands.set_led(on)
        async with self._operation("led", user=user):
            await self._write(payload)

    async def set_sleep(self, on: bool, *, user: bool = True) -> None:
        payload = commands.set_sleep(on)
        async with self._operation("sleep", user=user):
            await self._write(payload)

    async def set_timer_hours(self, hours: int, *, user: bool = True) -> None:
        payload = commands.set_timer_hours(hours)
        async with self._operation("timer", user=user):
            await self._write(payload)

    async def identify(
        self, blinks: int = IDENTIFY_BLINKS, *, user: bool = True
    ) -> None:
        """Blink the speed LEDs, then leave them as they were.

        Runs as one operation, so no other command lands mid-blink.
        """
        async with self._operation("identify", user=user):
            state = await self.async_refresh(user=user)
            original = state.led if state is not None else False
            try:
                for _ in range(blinks):
                    await self._write(commands.set_led(not original))
                    await asyncio.sleep(IDENTIFY_INTERVAL)
                    await self._write(commands.set_led(original))
                    await asyncio.sleep(IDENTIFY_INTERVAL)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await self._write(commands.set_led(original))
                raise

    # ---------------------------------------------------------------- reads
    async def async_refresh(self, *, user: bool = False) -> FanState | None:
        """Read the state and update `state` and `details`.

        The state string gives the series and the extra fields; the 4-byte
        state gives the flags and the timer, which the string lacks. A
        background read gives way to a user request waiting for its turn.
        """
        async with self._operation("read" if user else "background read", user=user):
            if not user and self._user_waiting:
                _LOGGER.debug("%s: background read gives way to a user request", self.address)
                return self.state
            text = (await self._read(STATE_CHAR)).decode(errors="ignore")
            details = decode_details(text)
            if details is not None:
                self.details = details
            if self.series is None:
                text_state = decode_state_string(text)
                if text_state is not None:
                    self.series = text_state.series
            st = decode_notification(await self._read(CMD_CHAR))
            self.last_read = monotonic()
            if st is not None:
                self._emit(st)
            return st

    async def read_wifi_status(self, *, user: bool = False) -> str | None:
        async with self._operation("wifi status", user=user):
            raw = await self._read(WIFI_STATUS_CHAR)
            try:
                return WIFI_STATUS.get(int(raw.decode(errors="ignore").strip()))
            except (ValueError, IndexError):
                return None
