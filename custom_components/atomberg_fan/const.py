"""Constants for the Atomberg Fan integration."""
from __future__ import annotations

DOMAIN = "atomberg_fan"

CONF_SERIES = "series"
CONF_DEVICE_ID = "device_id"
CONF_PERSISTENT = "persistent"

# Read the fan when the last read is older than this (seconds).
STALE_AFTER = 60.0
# How often to check whether a read is due (seconds).
CHECK_INTERVAL = 10
# A failed connection attempt counts towards the "can't connect" warning only
# if the fan advertised within this many seconds: Home Assistant takes minutes
# to notice a fan that went quiet, and that isn't the proxy's fault.
HEARD_RECENTLY = 30

# Series code -> model name.
MODELS = {"R1": "Renesa"}


def model_name(series: str | None) -> str:
    """The model's name, or its series code when unknown."""
    if not series:
        return "Fan"
    return MODELS.get(series, series)
