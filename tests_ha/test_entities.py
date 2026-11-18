"""Entry setup, reads and the entities."""
import asyncio

import pytest
from homeassistant.components.bluetooth import BluetoothChange
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from unittest.mock import patch

from custom_components.atomberg_fan.diagnostics import async_get_config_entry_diagnostics

from .conftest import make_entry, service_info


async def setup(hass, bluetooth, options=None):
    entry = make_entry(hass, options)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def heard(hass, adverts):
    adverts[-1](service_info(), BluetoothChange.ADVERTISEMENT)
    await hass.async_block_till_done()


async def settle(hass):
    await asyncio.sleep(0.01)  # idle disconnect
    await hass.async_block_till_done()


async def test_not_in_range_retries_setup(hass):
    entry = make_entry(hass)
    with patch("homeassistant.components.bluetooth.async_ble_device_from_address", return_value=None):
        await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_entities_are_unavailable_until_read(hass, bluetooth, client, adverts):
    await setup(hass, bluetooth)
    assert hass.states.get("fan.bedroom").state == "unavailable"

    await heard(hass, adverts)
    await settle(hass)
    fan = hass.states.get("fan.bedroom")
    assert fan.state == "off"
    assert fan.attributes["percentage"] == 0
    assert hass.states.get("light.bedroom_led").state == "off"
    assert hass.states.get("switch.bedroom_sleep_mode").state == "off"
    assert hass.states.get("select.bedroom_timer").state == "off"
    assert hass.states.get("sensor.bedroom_updated_last").state != "unknown"
    assert not client.is_connected  # connect-on-demand


async def test_reads_are_due_only_when_stale(hass, bluetooth, client, adverts):
    entry = await setup(hass, bluetooth)
    reads = []
    original = entry.runtime_data.fan.async_refresh

    async def counting(*args, **kwargs):
        reads.append(1)
        return await original(*args, **kwargs)

    with patch.object(entry.runtime_data.fan, "async_refresh", counting):
        await heard(hass, adverts)
        await settle(hass)
        await heard(hass, adverts)
        await settle(hass)
    assert len(reads) == 1


@pytest.mark.parametrize(
    ("service", "data", "write", "percentage", "preset"),
    [
        ("set_percentage", {"percentage": 40}, {"speed": 2}, 40, None),
        ("set_percentage", {"percentage": 100}, {"speed": 5}, 100, None),
        ("set_preset_mode", {"preset_mode": "boost"}, {"speed": 6}, 100, "boost"),
        ("turn_on", {}, {"power": True}, 80, None),
    ],
)
async def test_fan_controls(hass, bluetooth, client, adverts, service, data, write, percentage, preset):
    await setup(hass, bluetooth)
    await heard(hass, adverts)
    await settle(hass)

    await hass.services.async_call(
        "fan", service, {"entity_id": "fan.bedroom", **data}, blocking=True
    )
    await settle(hass)
    assert client.writes == [write]
    state = hass.states.get("fan.bedroom")
    assert state.state == "on"
    assert state.attributes["percentage"] == percentage
    assert state.attributes["preset_mode"] == preset

    client.writes.clear()
    await hass.services.async_call("fan", "turn_off", {"entity_id": "fan.bedroom"}, blocking=True)
    await settle(hass)
    assert client.writes == [{"power": False}]
    assert hass.states.get("fan.bedroom").state == "off"


async def test_led_sleep_and_timer(hass, bluetooth, client, adverts):
    await setup(hass, bluetooth)
    await heard(hass, adverts)
    await settle(hass)

    await hass.services.async_call("light", "turn_on", {"entity_id": "light.bedroom_led"}, blocking=True)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.bedroom_sleep_mode"}, blocking=True
    )
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.bedroom_timer", "option": "6h"}, blocking=True
    )
    await settle(hass)
    assert client.writes == [{"led": True}, {"sleep": True}, {"timer": 4}]
    assert hass.states.get("light.bedroom_led").state == "on"
    assert hass.states.get("switch.bedroom_sleep_mode").state == "on"
    assert hass.states.get("select.bedroom_timer").state == "6h"


async def test_remote_changes_show_while_connected(hass, bluetooth, client, adverts):
    await setup(hass, bluetooth, options={"persistent": True})
    await heard(hass, adverts)
    await settle(hass)
    assert client.is_connected  # stays connected

    client.flags = 0x13  # the remote: on, speed 3
    client.notify(None, client.state_bytes())
    await hass.async_block_till_done()
    assert hass.states.get("fan.bedroom").attributes["percentage"] == 60


async def test_unreachable_fan_shows_an_error(hass, bluetooth, client, adverts):
    await setup(hass, bluetooth)
    await heard(hass, adverts)
    await settle(hass)

    client.fail_connect = True
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call("fan", "turn_on", {"entity_id": "fan.bedroom"}, blocking=True)
    assert err.value.translation_key == "cannot_connect"


async def test_diagnostic_entities(hass, bluetooth, client, adverts):
    entry = await setup(hass, bluetooth)
    await heard(hass, adverts)
    await settle(hass)
    registry = er.async_get(hass)

    expected = {
        "sensor.bedroom_signal_strength": "-60",
        "sensor.bedroom_motor_speed": "240",
        "sensor.bedroom_voltage": "158.8",
        "sensor.bedroom_current": "0.93",
        "sensor.bedroom_board_temperature": "24.0",
        "sensor.bedroom_restarts": "4",
        "binary_sensor.bedroom_wi_fi_configured": "on",
    }
    for entity_id, value in expected.items():
        entity = registry.async_get(entity_id)
        assert entity is not None and entity.disabled_by is None, entity_id
        assert entity.entity_category == "diagnostic", entity_id
        assert hass.states.get(entity_id).state == value, entity_id

    runtime = hass.states.get("sensor.bedroom_runtime")
    assert runtime.attributes["unit_of_measurement"] == "h"
    assert round(float(runtime.state)) == 3206  # 11541641 s
    assert registry.async_get("sensor.bedroom_signal_strength").unique_id == (
        f"{entry.unique_id}_signal_strength"
    )
    for entity_id in ("sensor.bedroom_updated_last", "button.bedroom_identify",
                      "button.bedroom_update_status"):
        assert registry.async_get(entity_id).entity_category == "diagnostic", entity_id


async def test_connection_link_is_disabled_by_default_and_follows_the_link(
    hass, bluetooth, client, adverts
):
    entry = make_entry(hass, {"persistent": True})
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "binary_sensor", "atomberg_fan", f"{entry.unique_id}_connection_link",
        config_entry=entry, suggested_object_id="bedroom_connection_link", disabled_by=None,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.bedroom_connection_link").state == "off"

    await heard(hass, adverts)
    await settle(hass)
    assert hass.states.get("binary_sensor.bedroom_connection_link").state == "on"
    await client.disconnect()
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.bedroom_connection_link").state == "off"


async def test_connection_link_default(hass, bluetooth):
    await setup(hass, bluetooth)
    entity = er.async_get(hass).async_get("binary_sensor.bedroom_connection_link")
    assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_update_status_reads_now(hass, bluetooth, client, adverts):
    await setup(hass, bluetooth)
    await heard(hass, adverts)
    await settle(hass)
    reads = client.string_reads
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.bedroom_update_status"}, blocking=True
    )
    assert client.string_reads == reads + 1
    assert client.writes == []

    client.fail_connect = True
    await settle(hass)
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.bedroom_update_status"}, blocking=True
        )
    assert err.value.translation_key == "cannot_connect"


async def tick(hass, seconds):
    """Let the read timer run, as if `seconds` had passed."""
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await settle(hass)


async def test_reads_once_a_minute_without_new_adverts(hass, bluetooth, client, adverts, clock):
    entry = await setup(hass, bluetooth)
    await heard(hass, adverts)  # the one advert Home Assistant passes on
    await settle(hass)
    assert client.string_reads == 1

    clock[0] += 30
    await tick(hass, 11)
    assert client.string_reads == 1  # not due yet

    clock[0] += 31
    await tick(hass, 22)
    assert client.string_reads == 2  # a minute on: read, with no new advert
    assert not client.is_connected

    entry.runtime_data._available = False  # no longer heard
    clock[0] += 120
    await tick(hass, 33)
    assert client.string_reads == 2


async def test_failed_read_is_retried_a_minute_later(hass, bluetooth, client, adverts, clock):
    await setup(hass, bluetooth)
    client.fail_connect = True
    await heard(hass, adverts)
    await settle(hass)
    assert client.connects == 1

    clock[0] += 30
    await tick(hass, 11)
    assert client.connects == 1

    client.fail_connect = False
    clock[0] += 31
    await tick(hass, 22)
    assert client.connects == 2 and client.string_reads == 1


async def test_stay_connected_reads_once_a_minute_and_reconnects(
    hass, bluetooth, client, adverts, clock
):
    await setup(hass, bluetooth, options={"persistent": True})
    await heard(hass, adverts)
    await settle(hass)
    assert client.is_connected and client.string_reads == 1

    clock[0] += 61
    await tick(hass, 11)
    assert client.string_reads == 2 and client.connects == 1  # same link

    await client.disconnect()  # the link drops
    await tick(hass, 22)  # past the read cooldown
    assert client.is_connected and client.connects == 2


async def test_no_reconnect_after_unload(hass, bluetooth, client, adverts, clock):
    entry = await setup(hass, bluetooth, options={"persistent": True})
    await heard(hass, adverts)
    await settle(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    clock[0] += 120
    await tick(hass, 30)
    assert not client.is_connected and client.connects == 1


async def test_diagnostics(hass, bluetooth, client, adverts):
    entry = await setup(hass, bluetooth)
    await heard(hass, adverts)
    await settle(hass)
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["entry"]["data"]["address"] == "**REDACTED**"
    assert report["state"]["speed"] == 4 and report["state_raw0"] == "0x04"
    assert report["advertisement"]["rssi"] == -60


async def test_unload_disconnects(hass, bluetooth, client, adverts):
    entry = await setup(hass, bluetooth, options={"persistent": True})
    await heard(hass, adverts)
    await settle(hass)
    assert client.is_connected
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not client.is_connected


async def test_identify_button_blinks_the_leds(hass, bluetooth, client, adverts):
    await setup(hass, bluetooth)
    await heard(hass, adverts)
    await settle(hass)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.bedroom_identify"}, blocking=True
    )
    assert client.writes == [{"led": True}, {"led": False}] * 3
    assert er.async_get(hass).async_get("button.bedroom_identify").entity_category == "diagnostic"


async def test_heard_recently_names_the_proxy(hass, bluetooth, client, adverts):
    import time
    from types import SimpleNamespace

    entry = await setup(hass, bluetooth)
    heard = entry.runtime_data.fan._heard_recently
    assert heard() == "esp32-proxy"
    stale = SimpleNamespace(**{**vars(bluetooth), "time": time.monotonic() - 60})
    with patch("homeassistant.components.bluetooth.async_last_service_info", return_value=stale):
        assert heard() is None


async def test_connect_when_needed_never_subscribes(hass, bluetooth, client, adverts):
    await setup(hass, bluetooth)
    await heard(hass, adverts)
    await settle(hass)
    await hass.services.async_call("fan", "turn_on", {"entity_id": "fan.bedroom"}, blocking=True)
    await settle(hass)
    assert client.notify is None
    assert hass.states.get("fan.bedroom").state == "on"  # from the read-back


async def test_a_recent_read_pushes_back_the_background_read(hass, bluetooth, client, adverts, clock):
    await setup(hass, bluetooth)
    await heard(hass, adverts)
    await settle(hass)
    assert client.string_reads == 1

    clock[0] += 50
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.bedroom_update_status"}, blocking=True
    )
    assert client.string_reads == 2

    clock[0] += 20  # 70 s after the background read, 20 s after Update status
    await tick(hass, 11)
    assert client.string_reads == 2

    clock[0] += 41  # a minute after Update status
    await tick(hass, 22)
    assert client.string_reads == 3


async def test_a_failed_read_closes_the_link(hass, bluetooth, client, adverts):
    from custom_components.atomberg_fan.aioatombergfan.device import BleakError

    await setup(hass, bluetooth)
    await heard(hass, adverts)
    await settle(hass)

    async def _stuck(uuid):
        raise BleakError("read timed out")

    real = client.read_gatt_char
    client.read_gatt_char = _stuck
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.bedroom_update_status"}, blocking=True
        )
    assert not client.is_connected  # closed at once
    after_failure = client.connects

    client.read_gatt_char = real
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.bedroom_update_status"}, blocking=True
    )
    assert client.connects == after_failure + 1  # a fresh link
