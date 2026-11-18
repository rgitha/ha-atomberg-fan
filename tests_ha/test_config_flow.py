"""Config and options flows."""
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.atomberg_fan.const import DOMAIN

from .conftest import ADDRESS, make_entry, service_info

CF = "custom_components.atomberg_fan.config_flow"
MENU = ["identify", "setup_on_demand", "setup_persistent"]


def no_setup():
    return patch("custom_components.atomberg_fan.async_setup_entry", return_value=True)


def assert_menu(result, note=""):
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "confirm"
    assert result["menu_options"] == MENU
    assert result["description_placeholders"] == {
        "name": "Renesa (CD-26)", "address": ADDRESS, "note": note,
    }


async def discover(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=service_info()
    )
    assert_menu(result)
    return result


async def choose(hass, result, option):
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": option}
    )


async def finish_progress(hass, result):
    while result["type"] is FlowResultType.SHOW_PROGRESS:
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    return result


@pytest.mark.parametrize(
    ("option", "persistent"), [("setup_on_demand", False), ("setup_persistent", True)]
)
async def test_discovered_fan_is_added_as_chosen(hass, client, option, persistent):
    result = await discover(hass)
    with no_setup():
        result = await choose(hass, result, option)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Renesa"
    assert result["data"] == {"address": ADDRESS, "series": "R1", "device_id": "34cdb0c8cd24"}
    assert result["options"] == {"persistent": persistent}
    assert result["result"].unique_id == ADDRESS
    assert not client.is_connected  # link dropped after the check


async def test_setup_errors_show_as_a_note(hass, client):
    client.fail_connect = True
    result = await discover(hass)
    result = await choose(hass, result, "setup_on_demand")
    assert_menu(
        result,
        "\n\n**Couldn't connect. Move the fan's Bluetooth adapter or proxy closer and try again.**",
    )
    # The note shows once.
    client.fail_connect = False
    with no_setup():
        result = await choose(hass, result, "setup_on_demand")
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_blink_shows_progress_and_returns_to_the_menu(hass, client):
    result = await discover(hass)
    result = await choose(hass, result, "identify")
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["progress_action"] == "identifying"
    result = await finish_progress(hass, result)
    assert_menu(result)
    assert client.writes == [{"led": True}, {"led": False}] * 3
    assert not client.flags & 0x20  # LEDs left as they were


async def test_failed_blink_shows_a_note(hass, client):
    client.fail_connect = True
    result = await discover(hass)
    result = await finish_progress(hass, await choose(hass, result, "identify"))
    assert_menu(result, "\n\n**Couldn't blink its LEDs: the fan didn't respond.**")


async def test_discovery_of_a_configured_fan_aborts(hass):
    make_entry(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=service_info()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_discovery_of_another_device_aborts(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_BLUETOOTH},
        data=service_info(name="Atomberg"),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_picking_a_fan_opens_the_menu(hass, client):
    other = service_info(address="AA:BB:CC:DD:EE:FF", name="Some lamp")
    with patch(f"{CF}.async_discovered_service_info", return_value=[service_info(), other]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["step_id"] == "user"
    assert [str(k) for k in result["data_schema"].schema] == ["address"]
    choices = result["data_schema"].schema["address"].container
    assert choices == {ADDRESS: "Renesa (CD-26)", "manual": "Enter an address"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"address": ADDRESS})
    assert_menu(result)
    with no_setup():
        result = await choose(hass, result, "setup_persistent")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {"persistent": True}


async def test_configured_fans_are_not_listed(hass):
    make_entry(hass)
    with patch(f"{CF}.async_discovered_service_info", return_value=[service_info()]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["step_id"] == "manual"


async def test_entering_an_address_opens_the_menu(hass, client):
    with patch(f"{CF}.async_discovered_service_info", return_value=[]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["step_id"] == "manual"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"address": "not-an-address"}
    )
    assert result["errors"] == {"address": "invalid_address"}

    with patch(f"{CF}.async_last_service_info", return_value=None):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"address": "aa-bb-cc-dd-ee-ff"}
        )
    assert result["errors"] == {"base": "not_found"}

    with patch(f"{CF}.async_last_service_info", return_value=service_info()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"address": ADDRESS.lower().replace(":", "-")}
        )
    assert_menu(result)
    with no_setup():
        result = await choose(hass, result, "setup_on_demand")
    assert result["data"]["address"] == ADDRESS


async def test_entering_the_address_of_an_added_fan_aborts(hass):
    make_entry(hass)
    with patch(f"{CF}.async_discovered_service_info", return_value=[]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    with patch(f"{CF}.async_last_service_info", return_value=service_info()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"address": ADDRESS}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_configure_changes_stay_connected(hass):
    entry = make_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    with patch.object(hass.config_entries, "async_reload"):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"persistent": True}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"persistent": True}
