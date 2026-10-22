"""Power actions use real HA scripts and never optimistically report success."""

import asyncio
from dataclasses import replace
from unittest.mock import patch

import pytest
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.haier_tv.api import (
    AuthenticationError,
    CannotConnect,
    InvalidResponse,
)
from custom_components.haier_tv.diagnostics import async_get_config_entry_diagnostics

OPTIONS = {
    "turn_on_action": [{"event": "tv_ir"}],
    "turn_off_action": [{"event": "tv_ir"}],
    "offline_as_off": True,
    "turn_off_mode": "action",
    "power_timeout": 120,
}


async def configure(hass, entry, **options):
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options=OPTIONS | options)


async def setup(hass, entry):
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return {
        e.unique_id.rsplit("_", 1)[-1]: e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


async def test_options(hass, entry, client):
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], OPTIONS | {"turn_off_action": []}
    )
    assert result["errors"] == {"turn_off_action": "action_required"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], OPTIONS | {"turn_on_action": [{"invalid": True}]}
    )
    assert result["errors"] == {"base": "invalid_action"}
    with patch("custom_components.haier_tv.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], OPTIONS
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == OPTIONS


async def test_offline_start_and_wake(hass, entry, client):
    await configure(hass, entry)
    awake = client.async_read.return_value
    client.info = None
    client.async_read.side_effect = CannotConnect()
    ids = await setup(hass, entry)
    assert hass.states.get(ids["tv"]).state == "off"
    assert hass.states.get(ids["connection"]).state == "off"
    assert hass.states.get(ids["maxxbass"]).state == "unavailable"
    assert (await async_get_config_entry_diagnostics(hass, entry))["state"] is None
    fired = []

    @callback
    def ir(event):
        fired.append(event)
        client.async_read.side_effect = None
        client.async_read.return_value = awake

    remove = hass.bus.async_listen("tv_ir", ir)
    await hass.services.async_call(
        "media_player", "turn_on", {"entity_id": ids["tv"]}, blocking=True
    )
    assert len(fired) == 1
    assert hass.states.get(ids["tv"]).state == "on"
    await hass.services.async_call(
        "media_player", "turn_on", {"entity_id": ids["tv"]}, blocking=True
    )
    assert len(fired) == 1
    remove()


@pytest.mark.parametrize("mode", ["adb", "action"])
async def test_off_confirmation(hass, entry, client, mode):
    await configure(hass, entry, turn_off_mode=mode)
    ids = await setup(hass, entry)
    off = replace(client.async_read.return_value, screen=False)

    async def sleep():
        client.async_read.side_effect = CannotConnect()
        raise CannotConnect("standby closed the transport")

    client.async_sleep.side_effect = sleep

    @callback
    def ir(event):
        client.async_read.return_value = off

    remove = hass.bus.async_listen("tv_ir", ir)
    await hass.services.async_call(
        "media_player", "turn_off", {"entity_id": ids["tv"]}, blocking=True
    )
    assert hass.states.get(ids["tv"]).state == "off"
    assert client.async_sleep.await_count == (mode == "adb")
    remove()


async def test_pending_no_optimism_duplicates_and_unload(hass, entry, client):
    await configure(hass, entry)
    client.async_read.side_effect = CannotConnect()
    ids = await setup(hass, entry)
    coord = entry.runtime_data
    fired = asyncio.Event()
    remove = hass.bus.async_listen("tv_ir", callback(lambda event: fired.set()))
    task = asyncio.create_task(coord.async_power(True, None))
    await fired.wait()
    assert not task.done()
    assert hass.states.get(ids["tv"]).state == "off"
    assert hass.states.get(ids["tv"]).attributes["power_transition"] == "turning_on"
    with pytest.raises(HomeAssistantError, match="already in progress"):
        await coord.async_power(True, None)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert task.cancelled()
    calls = client.async_read.await_count
    with pytest.raises(HomeAssistantError, match="stopped"):
        await coord.async_power(True, None)
    assert client.async_read.await_count == calls
    client.async_close.assert_awaited_once()
    remove()


async def test_timeout_and_auth_error(hass, entry, client):
    await configure(hass, entry)
    client.async_read.side_effect = CannotConnect()
    ids = await setup(hass, entry)
    coord = entry.runtime_data
    coord.power_timeout = 0.01
    with pytest.raises(HomeAssistantError, match="Timed out"):
        await coord.async_power(True, None)
    assert coord.power_transition is None
    assert hass.states.get(ids["tv"]).state == "off"
    client.async_read.side_effect = AuthenticationError("authorize")
    with pytest.raises(HomeAssistantError, match="authorize"):
        await coord.async_power(True, None)
    assert hass.states.get(ids["tv"]).state == "unavailable"


async def test_online_but_screen_off_does_not_confirm_wake(hass, entry, client):
    await configure(hass, entry)
    client.async_read.return_value = replace(
        client.async_read.return_value, screen=False
    )
    await setup(hass, entry)
    coord = entry.runtime_data
    coord.power_timeout = 0.01
    with pytest.raises(HomeAssistantError, match="Timed out"):
        await coord.async_power(True, None)


async def test_action_failure(hass, entry, client):
    await configure(hass, entry, turn_on_action=[{"action": "missing.action"}])
    client.async_read.side_effect = CannotConnect()
    await setup(hass, entry)
    with pytest.raises(HomeAssistantError):
        await entry.runtime_data.async_power(True, None)
    assert entry.runtime_data.power_transition is None


async def test_unconfigured_power_rejected(hass, entry, client):
    await setup(hass, entry)
    for on in (True, False):
        with pytest.raises(HomeAssistantError):
            await entry.runtime_data.async_power(on, None)


async def test_protocol_error_not_off(hass, entry, client):
    await configure(hass, entry)
    ids = await setup(hass, entry)
    client.async_read.side_effect = InvalidResponse("bad parcel")
    await entry.runtime_data.async_refresh()
    assert hass.states.get(ids["tv"]).state == "unavailable"


async def test_unload_cancels_running_action_sequence(hass, entry, client):
    await configure(
        hass,
        entry,
        turn_on_action=[{"event": "tv_ir"}, {"delay": 60}, {"event": "must_not_run"}],
    )
    client.async_read.side_effect = CannotConnect()
    await setup(hass, entry)
    coord = entry.runtime_data
    fired = asyncio.Event()
    later = []
    remove_ir = hass.bus.async_listen("tv_ir", callback(lambda event: fired.set()))
    remove_later = hass.bus.async_listen(
        "must_not_run", callback(lambda event: later.append(event))
    )
    task = asyncio.create_task(coord.async_power(True, None))
    await fired.wait()
    assert coord.scripts["turn_on_action"].is_running
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert task.cancelled()
    assert not coord.scripts["turn_on_action"].is_running
    assert not later
    remove_ir()
    remove_later()


async def test_options_reload_closes_old_connection(hass, entry, client):
    await setup(hass, entry)
    old = entry.runtime_data
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(flow["flow_id"], OPTIONS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert old._stopped
    assert entry.runtime_data is not old
    client.async_close.assert_awaited_once()
    assert "turn_on_action" in entry.runtime_data.scripts
