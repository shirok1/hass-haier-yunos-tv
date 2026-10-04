"""Key persistence, off-loop initialization and authentication failure handling."""

from unittest.mock import Mock, patch

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.haier_tv.api import AuthenticationError
from custom_components.haier_tv.coordinator import (
    HaierCoordinator,
    _load_signer,
    async_create_client,
)


def test_key_persistence(tmp_path):
    key = tmp_path / "storage" / "haier_tv_adbkey"
    first = _load_signer(key)
    private = key.read_bytes()
    second = _load_signer(key)
    assert key.read_bytes() == private
    assert first.GetPublicKey() == second.GetPublicKey()
    assert key.stat().st_mode & 0o777 == 0o600
    assert key.with_suffix(".pub").stat().st_mode & 0o777 == 0o600


async def test_client_factory(hass):
    signer = Mock()
    with (
        patch(
            "custom_components.haier_tv.coordinator._load_signer", return_value=signer
        ),
        patch("custom_components.haier_tv.coordinator.HaierClient") as client,
    ):
        assert (
            await async_create_client(hass, "192.0.2.1", 5555, "device-id")
            is client.return_value
        )
        client.assert_called_once_with("192.0.2.1", 5555, signer, "device-id")


async def test_auth_requests_reauth(hass, entry, client):
    coordinator = HaierCoordinator(hass, entry, client)
    client.async_read.side_effect = AuthenticationError()
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_stop_releases_transport(hass, entry, client):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    client.async_close.assert_awaited_once()
