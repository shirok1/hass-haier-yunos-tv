"""HA fixtures and captured-protocol fixtures; no live television access."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haier_tv.api import DeviceInfo, HaierClient, Snapshot
from custom_components.haier_tv.const import DOMAIN, MODEL


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Allow loading the local custom component in HA."""
    yield


@pytest.fixture
def entry():
    return MockConfigEntry(
        domain=DOMAIN,
        title=MODEL,
        unique_id="00:11:22:33:44:55",
        data={"host": "192.0.2.1", "port": 5555},
    )


@pytest.fixture
def client():
    client = AsyncMock(spec=HaierClient)
    client.info = DeviceInfo("00:11:22:33:44:55", MODEL, "test-firmware")
    state = Snapshot(16, 10, False, 10, True, True, False, "1080p 60Hz")
    client.async_read.return_value = state

    async def write(operation, value):
        nonlocal state
        if operation == "source":
            value = {"HDMI1": 16, "HDMI2": 17, "HDMI3": 18}[value]
        state = replace(state, **{operation: value})
        client.async_read.return_value = state
        return state

    client.async_write.side_effect = write
    with (
        patch("custom_components.haier_tv.async_create_client", return_value=client),
        patch(
            "custom_components.haier_tv.config_flow.async_create_client",
            return_value=client,
        ),
    ):
        yield client
