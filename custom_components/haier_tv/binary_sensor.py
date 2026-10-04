"""Screen, signal and native connection diagnostics."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HaierConfigEntry, HaierCoordinator
from .entity import HaierEntity

PARALLEL_UPDATES = 0
DESCRIPTIONS = (
    BinarySensorEntityDescription(key="screen", translation_key="screen"),
    BinarySensorEntityDescription(key="signal", translation_key="signal"),
    BinarySensorEntityDescription(
        key="connection",
        translation_key="connection",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaierConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        HaierBinarySensor(entry.runtime_data, desc) for desc in DESCRIPTIONS
    )


class HaierBinarySensor(HaierEntity, BinarySensorEntity):
    """Connectivity remains readable when the other entities become unavailable."""

    def __init__(
        self, coordinator: HaierCoordinator, description: BinarySensorEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return self.entity_description.key == "connection" or super().available

    @property
    def is_on(self) -> bool:
        match self.entity_description.key:
            case "connection":
                return self.coordinator.last_update_success
            case "signal":
                return not self.coordinator.data.no_signal
            case _:
                return self.coordinator.data.screen
