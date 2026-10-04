"""Shared device identity and availability."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HaierCoordinator


class HaierEntity(CoordinatorEntity[HaierCoordinator]):
    """An entity on the single TV device, with a stable hardware-derived ID."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HaierCoordinator, key: str) -> None:
        super().__init__(coordinator)
        info = coordinator.client.info
        assert info is not None
        self._attr_unique_id = f"{info.unique_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, info.unique_id)},
            name=info.model,
            manufacturer="Haier",
            model=info.model,
            sw_version=info.fingerprint or None,
        )
