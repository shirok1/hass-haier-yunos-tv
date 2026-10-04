"""Only the requested MaxxBass effect and basic mute control."""

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HaierConfigEntry, HaierCoordinator
from .entity import HaierEntity

PARALLEL_UPDATES = 0
DESCRIPTIONS = (
    SwitchEntityDescription(key="maxxbass", translation_key="maxxbass"),
    SwitchEntityDescription(key="mute", translation_key="mute"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaierConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(HaierSwitch(entry.runtime_data, desc) for desc in DESCRIPTIONS)


class HaierSwitch(HaierEntity, SwitchEntity):
    """A switch driven by actual Binder readback."""

    def __init__(
        self, coordinator: HaierCoordinator, description: SwitchEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return getattr(self.coordinator.data, self.entity_description.key)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_control(self.entity_description.key, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_control(self.entity_description.key, 0)
