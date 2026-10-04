"""Load the real HA platforms and exercise their public services."""

from dataclasses import replace

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.haier_tv.api import CannotConnect, WriteNotApplied
from custom_components.haier_tv.diagnostics import async_get_config_entry_diagnostics


async def setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    return {
        e.unique_id.rsplit("_", 1)[-1]: e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }


async def test_setup_entities_and_controls(hass, entry, client):
    ids = await setup(hass, entry)
    assert len(ids) == 10
    assert hass.states.get(ids["tv"]).state == "on"
    assert hass.states.get(ids["tv"]).attributes["volume_level"] == 0.1
    assert hass.states.get(ids["tv"]).attributes["source"] == "HDMI1"
    assert hass.states.get(ids["maxxbass"]).state == "on"
    assert hass.states.get(ids["backlight"]).state == "10"
    assert hass.states.get(ids["resolution"]).state == "1080p 60Hz"
    assert len(dr.async_get(hass).devices) == 1
    for domain, service, key, data, expected in [
        ("media_player", "volume_set", "tv", {"volume_level": 0.25}, ("volume", 25)),
        ("media_player", "volume_mute", "tv", {"is_volume_muted": True}, ("mute", 1)),
        (
            "media_player",
            "select_source",
            "tv",
            {"source": "HDMI2"},
            ("source", "HDMI2"),
        ),
        ("number", "set_value", "backlight", {"value": 7}, ("backlight", 7)),
        ("switch", "turn_off", "maxxbass", {}, ("maxxbass", 0)),
        ("switch", "turn_on", "maxxbass", {}, ("maxxbass", 1)),
        ("switch", "turn_off", "mute", {}, ("mute", 0)),
    ]:
        await hass.services.async_call(
            domain, service, {"entity_id": ids[key], **data}, blocking=True
        )
        await hass.async_block_till_done()
        client.async_write.assert_awaited_with(*expected)
    assert hass.states.get(ids["tv"]).attributes["volume_level"] == 0.25
    assert hass.states.get(ids["backlight"]).state == "7"
    assert hass.states.get(ids["tv"]).attributes["source"] == "HDMI2"
    await hass.services.async_call(
        "button", "press", {"entity_id": ids["refresh"]}, blocking=True
    )
    assert client.async_read.await_count >= 2
    assert await hass.config_entries.async_unload(entry.entry_id)
    client.async_close.assert_awaited_once()


async def test_failure_availability_recovery_and_diagnostics(hass, entry, client):
    ids = await setup(hass, entry)
    client.async_read.side_effect = CannotConnect("disconnected")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ids["tv"]).state == "unavailable"
    assert hass.states.get(ids["maxxbass"]).state == "unavailable"
    assert hass.states.get(ids["connection"]).state == "off"
    client.async_read.side_effect = None
    client.async_read.return_value = replace(
        client.async_read.return_value, no_signal=True
    )
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ids["tv"]).state == "on"
    assert hass.states.get(ids["signal"]).state == "off"
    assert hass.states.get(ids["resolution"]).state == "unavailable"
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["config"]["host"] == "**REDACTED**"
    assert report["device"]["unique_id"] == "**REDACTED**"
    assert "192.0.2.1" not in str(report)


async def test_write_failure_not_optimistic(hass, entry, client):
    ids = await setup(hass, entry)
    client.async_write.side_effect = WriteNotApplied(
        "maxxbass", 0, client.async_read.return_value
    )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": ids["maxxbass"]}, blocking=True
        )
    assert hass.states.get(ids["maxxbass"]).state == "on"
    client.async_write.side_effect = CannotConnect("disconnected")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": ids["maxxbass"]}, blocking=True
        )
    await hass.async_block_till_done()
    assert hass.states.get(ids["maxxbass"]).state == "unavailable"


async def test_setup_failure_releases_connection(hass, entry, client):
    entry.add_to_hass(hass)
    client.async_read.side_effect = CannotConnect("offline")
    assert not await hass.config_entries.async_setup(entry.entry_id)
    client.async_close.assert_awaited_once()


async def test_disabling_entry_stops_polling_and_closes_adb(hass, entry, client):
    """Exercise the real HA disable operation, not just the unload callback."""
    from datetime import timedelta

    from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    ids = await setup(hass, entry)
    coordinator = entry.runtime_data
    assert await hass.config_entries.async_set_disabled_by(
        entry.entry_id, ConfigEntryDisabler.USER
    )
    await hass.async_block_till_done()
    client.async_close.assert_awaited_once()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert coordinator._shutdown_requested
    assert coordinator._unsub_refresh is None
    assert hass.states.get(ids["tv"]).state == "unavailable"
    reads = client.async_read.await_count
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2))
    await hass.async_block_till_done()
    assert client.async_read.await_count == reads
