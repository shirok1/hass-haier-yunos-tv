"""Backlight adjustment for the active input."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HaierConfigEntry, HaierCoordinator
from .entity import HaierEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaierConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([HaierBacklight(entry.runtime_data)])


class HaierBacklight(HaierEntity, NumberEntity):
    """Hardware backlight, whose range is 0–10 rather than 0–100."""

    _attr_translation_key = "backlight"
    _attr_native_min_value = 0
    _attr_native_max_value = 10
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: HaierCoordinator) -> None:
        super().__init__(coordinator, "backlight")

    @property
    def native_value(self) -> float:
        return self.coordinator.data.backlight

    async def async_set_native_value(self, value: float) -> None:
        if not float(value).is_integer() or not 0 <= value <= 10:
            raise ServiceValidationError("Backlight must be an integer from 0 to 10")
        await self.coordinator.async_control("backlight", int(value))
