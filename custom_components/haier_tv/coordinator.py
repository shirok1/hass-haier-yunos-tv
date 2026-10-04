"""Connection setup and shared polling for Haier TV entities."""

import asyncio
import logging
from pathlib import Path

from adb_shell.auth.keygen import keygen
from adb_shell.auth.sign_pythonrsa import PythonRSASigner
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthenticationError, HaierClient, HaierError, Snapshot, WriteNotApplied
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


def _load_signer(path: Path) -> PythonRSASigner:
    """Generate/load the ADB key off the event loop, like HA's ADB integration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        keygen(str(path))
        path.chmod(0o600)
        path.with_suffix(".pub").chmod(0o600)
    return PythonRSASigner.FromRSAKeyPath(str(path))


async def async_create_client(
    hass: HomeAssistant, host: str, port: int, expected_id: str | None = None
) -> HaierClient:
    """Serialize key creation across concurrent configuration flows."""
    key_lock = hass.data.setdefault(DOMAIN, asyncio.Lock())
    async with key_lock:
        signer = await hass.async_add_executor_job(
            _load_signer, Path(hass.config.path(STORAGE_DIR, "haier_tv_adbkey"))
        )
    return HaierClient(host, port, signer, expected_id)


class HaierCoordinator(DataUpdateCoordinator[Snapshot]):
    """Read a full native snapshot once for every entity."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: HaierClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self.client = client

    async def _async_update_data(self) -> Snapshot:
        try:
            return await self.client.async_read()
        except AuthenticationError as exc:
            raise ConfigEntryAuthFailed("Authorize Home Assistant on the TV") from exc
        except HaierError as exc:
            raise UpdateFailed(str(exc)) from exc

    async def async_control(self, operation: str, value: int | str) -> None:
        """Publish actual readback, and surface failed operations to the caller."""
        try:
            snapshot = await self.client.async_write(operation, value)
        except WriteNotApplied as exc:
            self.async_set_updated_data(exc.state)
            raise HomeAssistantError(str(exc)) from exc
        except (HaierError, ValueError) as exc:
            if isinstance(exc, HaierError):
                self.async_set_update_error(UpdateFailed(str(exc)))
            raise HomeAssistantError(str(exc)) from exc
        self.async_set_updated_data(snapshot)


type HaierConfigEntry = ConfigEntry[HaierCoordinator]
