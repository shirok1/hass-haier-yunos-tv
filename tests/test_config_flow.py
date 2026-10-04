"""Exercise HA's real configuration flow including duplicate and conflict paths."""

from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haier_tv.api import (
    AuthenticationError,
    CannotConnect,
    InvalidResponse,
    UnsupportedDevice,
)
from custom_components.haier_tv.const import DOMAIN


async def test_user_flow(hass, client):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    with patch("custom_components.haier_tv.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.0.2.1", "port": 5555}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "00:11:22:33:44:55"
    client.async_close.assert_awaited_once()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (CannotConnect(), "cannot_connect"),
        (AuthenticationError(), "auth_failed"),
        (UnsupportedDevice(), "unsupported_device"),
        (InvalidResponse(), "invalid_response"),
    ],
)
async def test_connection_errors(hass, client, error, expected):
    client.async_read.side_effect = error
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={"host": "192.0.2.1", "port": 5555}
    )
    assert result["errors"] == {"base": expected}
    client.async_close.assert_awaited_once()


async def test_duplicate_host_does_not_connect(hass, entry, client):
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=dict(entry.data)
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    client.async_read.assert_not_awaited()


async def test_duplicate_hardware_at_new_address(hass, entry, client):
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={"host": "192.0.2.2", "port": 5555}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_existing_adb_owner(hass, client):
    MockConfigEntry(
        domain="androidtv", data={"host": "192.0.2.1", "port": 5555}
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={"host": "192.0.2.1", "port": 5555}
    )
    assert result["errors"] == {"base": "adb_in_use"}
    client.async_read.assert_not_awaited()


async def test_reconfigure(hass, entry, client):
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    assert result["type"] is FlowResultType.FORM
    with patch("custom_components.haier_tv.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.0.2.2", "port": 5555}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["host"] == "192.0.2.2"


async def test_reauth(hass, entry, client):
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
        data=dict(entry.data),
    )
    assert result["step_id"] == "reauth_confirm"
    with patch("custom_components.haier_tv.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
