"""Redacted device and coordinator diagnostics, never ADB keys or raw shells."""

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import HaierConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HaierConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    assert coordinator.client.info is not None
    return {
        "config": async_redact_data(dict(entry.data), {"host"}),
        "device": async_redact_data(asdict(coordinator.client.info), {"unique_id"}),
        "last_update_success": coordinator.last_update_success,
        "state": asdict(coordinator.data),
    }
