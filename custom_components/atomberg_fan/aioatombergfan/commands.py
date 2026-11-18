"""Build Atomberg command payloads (plain JSON, one setting per command).

Verified on the R1: the fan ignores a command carrying two settings
(e.g. power+speed together), so each command sets exactly one thing.
`{"speed": N}` also powers the fan on if it is off.
"""

from __future__ import annotations

import json

from .const import MAX_SPEED, MIN_SPEED, TIMER_HOURS_TO_VALUE


def _enc(d: dict[str, object]) -> bytes:
    return json.dumps(d, separators=(",", ":")).encode()


def set_power(on: bool) -> bytes:
    return _enc({"power": bool(on)})


def set_speed(speed: int) -> bytes:
    if not MIN_SPEED <= speed <= MAX_SPEED:
        raise ValueError(f"speed must be {MIN_SPEED}-{MAX_SPEED}")
    return _enc({"speed": speed})  # also powers on if off


def set_led(on: bool) -> bytes:
    return _enc({"led": bool(on)})


def set_sleep(on: bool) -> bytes:
    return _enc({"sleep": bool(on)})


def set_timer_hours(hours: int) -> bytes:
    if hours not in TIMER_HOURS_TO_VALUE:
        raise ValueError(f"timer hours must be one of {sorted(TIMER_HOURS_TO_VALUE)}")
    return _enc({"timer": TIMER_HOURS_TO_VALUE[hours]})


def read_state() -> bytes:
    return _enc({"read": 1})
