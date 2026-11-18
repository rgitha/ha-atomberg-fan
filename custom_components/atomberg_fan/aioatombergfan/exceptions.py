"""Exceptions raised by aioatombergfan."""

from __future__ import annotations


class AtombergError(Exception):
    """Base class for all aioatombergfan errors."""


class DeviceBusy(AtombergError):
    """A user request could not get its turn and a link in time.

    Another exchange held the device; the caller should try again.
    """


class NotConnected(AtombergError):
    """An operation ran but the BLE link could not be established."""
