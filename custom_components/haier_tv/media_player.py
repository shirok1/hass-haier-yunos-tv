"""Native source and TV amplifier controls, not Android music-stream volume."""

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

    @property
    def state(self) -> MediaPlayerState:
        return (
            MediaPlayerState.ON
            if self.coordinator.data.screen
            else MediaPlayerState.OFF
        )

    @property
    def source(self) -> str:
        value = self.coordinator.data.source
        return SOURCE_NAMES.get(value, f"Unknown ({value})")

    @property
    def volume_level(self) -> float:
        return self.coordinator.data.volume / 100

    @property
    def is_volume_muted(self) -> bool:
        return self.coordinator.data.mute

    async def async_select_source(self, source: str) -> None:
        await self.coordinator.async_control("source", source)

    async def async_set_volume_level(self, volume: float) -> None:
        await self.coordinator.async_control("volume", volume_percent(volume))

    async def async_mute_volume(self, mute: bool) -> None:
        await self.coordinator.async_control("mute", int(mute))
