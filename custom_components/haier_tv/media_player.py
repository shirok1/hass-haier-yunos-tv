"""Native source and TV amplifier controls, not Android music-stream volume."""

from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import volume_percent
from .const import SOURCE_NAMES, SOURCES
from .coordinator import HaierConfigEntry, HaierCoordinator
from .entity import HaierEntity

PARALLEL_UPDATES = 0  # The client serializes all platforms' ADB transactions.


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaierConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([HaierMediaPlayer(entry.runtime_data)])


class HaierMediaPlayer(HaierEntity, MediaPlayerEntity):
    """The television's actual source, screen state and amplifier."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = (
        MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
    )
    _attr_source_list = list(SOURCES)

    def __init__(self, coordinator: HaierCoordinator) -> None:
        super().__init__(coordinator, "tv")
        if "turn_on_action" in coordinator.scripts:
            self._attr_supported_features |= MediaPlayerEntityFeature.TURN_ON
        if coordinator.off_mode != "disabled":
            self._attr_supported_features |= MediaPlayerEntityFeature.TURN_OFF

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and (
            self.coordinator.data is not None or self.coordinator.offline_as_off
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"power_transition": self.coordinator.power_transition}

    async def async_turn_on(self) -> None:
        await self.coordinator.async_power(True, self._context)

    async def async_turn_off(self) -> None:
        await self.coordinator.async_power(False, self._context)

    @property
    def state(self) -> MediaPlayerState:
        return (
            MediaPlayerState.ON
            if self.coordinator.data is not None and self.coordinator.data.screen
            else MediaPlayerState.OFF
        )

    @property
    def source(self) -> str | None:
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.source
        return SOURCE_NAMES.get(value, f"Unknown ({value})")

    @property
    def volume_level(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.volume / 100

    @property
    def is_volume_muted(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.mute

    async def async_select_source(self, source: str) -> None:
        await self.coordinator.async_control("source", source)

    async def async_set_volume_level(self, volume: float) -> None:
        await self.coordinator.async_control("volume", volume_percent(volume))

    async def async_mute_volume(self, mute: bool) -> None:
        await self.coordinator.async_control("mute", int(mute))
