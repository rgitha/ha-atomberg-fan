"""Decode Atomberg fan state (verified on R1 / Renesa)."""

from __future__ import annotations

from dataclasses import dataclass

from .const import (
    BIT_BOOST,
    BIT_LED,
    BIT_POWER,
    BIT_SLEEP,
    MASK_SPEED,
)


@dataclass
class FanState:
    power: bool
    speed: int  # 1-6; 6 == boost
    boost: bool
    led: bool
    sleep: bool
    timer_hours: int  # 0/1/2/3/6
    series: str | None = None
    raw0: int = 0  # byte 0 / state-string field 0

    @property
    def is_boost(self) -> bool:
        return self.boost or self.speed == 6


def _decode_flags(field0: int, timer_hours: int, series: str | None) -> FanState:
    return FanState(
        power=bool(field0 & BIT_POWER),
        speed=field0 & MASK_SPEED,
        boost=bool(field0 & BIT_BOOST),
        led=bool(field0 & BIT_LED),
        sleep=bool(field0 & BIT_SLEEP),
        timer_hours=timer_hours,
        series=series,
        raw0=field0,
    )


def decode_notification(data: bytes) -> FanState | None:
    """Decode a 4-byte notification/read from CMD_CHAR.

    byte0 = flags, byte1 = brightness (R1: always 0), byte2 = timer hours, byte3 = 0.
    """
    if len(data) < 3:
        return None
    return _decode_flags(data[0], data[2], None)


def decode_state_string(text: str) -> FanState | None:
    """Decode the comma-separated string from STATE_CHAR.

    Field 0 = same flags as notification byte 0; field 7 = series code.
    Returns None for non-state replies (e.g. an error string).
    """
    parts = text.split(",")
    field0 = parts[0].strip()
    if not field0.lstrip("-").isdigit():
        return None
    v = int(field0)
    series = parts[7].strip() if len(parts) > 7 else None
    # Timer hours aren't in the flag byte of the string; use 0 unless a
    # notification supplies it. (The string carries timer in later fields that
    # we don't rely on here.)
    return _decode_flags(v, 0, series)


def _field(parts: list[str], index: int) -> str | None:
    if index >= len(parts):
        return None
    value = parts[index].strip()
    return value if value and value != "END" else None


def _num(parts: list[str], index: int) -> float | None:
    value = _field(parts, index)
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _int(parts: list[str], index: int) -> int | None:
    value = _num(parts, index)
    return int(value) if value is not None else None


@dataclass
class FanDetails:
    """Extra fields of the state string. Meanings are best guesses,
    not yet confirmed (see PROTOCOL.md)."""

    raw: str
    voltage: float | None = None  # field 4: changes with speed
    rpm: int | None = None  # field 6: changes with speed
    restarts: int | None = None  # field 9: +1 after a Wi-Fi reset
    runtime_s: int | None = None  # field 11
    current: float | None = None  # field 15
    board_temp: float | None = None  # field 16, degrees C
    wifi_configured: bool | None = None  # field 17: 0 -> 1 after a credential write


def decode_details(text: str) -> FanDetails | None:
    """Decode the extra fields of the state string; None if it isn't one."""
    parts = text.split(",")
    if not parts[0].strip().lstrip("-").isdigit():
        return None
    wifi = _int(parts, 17)
    return FanDetails(
        raw=text.strip(),
        voltage=_num(parts, 4),
        rpm=_int(parts, 6),
        restarts=_int(parts, 9),
        runtime_s=_int(parts, 11),
        current=_num(parts, 15),
        board_temp=_num(parts, 16),
        wifi_configured=None if wifi is None else bool(wifi),
    )
