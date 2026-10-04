"""Input and resolution diagnostics."""

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SOURCE_NAMES
from .coordinator import HaierConfigEntry, HaierCoordinator
from .entity import HaierEntity

PARALLEL_UPDATES = 0
DESCRIPTIONS = (
    SensorEntityDescription(key="source", translation_key="source"),
    SensorEntityDescription(
        key="resolution",
        translation_key="resolution",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaierConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(HaierSensor(entry.runtime_data, desc) for desc in DESCRIPTIONS)


class HaierSensor(HaierEntity, SensorEntity):
    """Read-only information from the native TV service."""

    def __init__(
        self, coordinator: HaierCoordinator, description: SensorEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if self.entity_description.key == "resolution":
            return (
                not self.coordinator.data.no_signal
                and self.coordinator.data.resolution is not None
            )
        return True

    @property
    def native_value(self) -> str | None:
        if self.entity_description.key == "source":
            source = self.coordinator.data.source
            return SOURCE_NAMES.get(source, f"Unknown ({source})")
        return self.coordinator.data.resolution
