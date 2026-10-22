"""Connection setup and shared polling for Haier TV entities."""

import asyncio
import logging
from pathlib import Path

from adb_shell.auth.keygen import keygen
from adb_shell.auth.sign_pythonrsa import PythonRSASigner
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.script import Script, async_validate_actions_config
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AuthenticationError,
    CannotConnect,
    DeviceInfo,
    HaierClient,
    HaierError,
    Snapshot,
    WriteNotApplied,
)
from .const import DOMAIN, MODEL, UPDATE_INTERVAL

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


class HaierCoordinator(DataUpdateCoordinator[Snapshot | None]):
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
        self.entry = entry
        self.offline_as_off = bool(entry.options.get("offline_as_off", False))
        self.off_mode = entry.options.get("turn_off_mode", "disabled")
        self.power_timeout = entry.options.get("power_timeout", 120)
        self.scripts: dict[str, Script] = {}
        self.power_transition: str | None = None
        self._power_task: asyncio.Task | None = None
        self._stopped = False

    @property
    def device_info(self) -> DeviceInfo:
        """Known entries can start while their already-validated TV is off."""
        return self.client.info or DeviceInfo(
            self.entry.unique_id or "", MODEL, self.entry.data.get("fingerprint", "")
        )

    async def async_setup_power(self) -> None:
        for key in ("turn_on_action", "turn_off_action"):
            if sequence := self.entry.options.get(key):
                sequence = await async_validate_actions_config(
                    self.hass, cv.SCRIPT_SCHEMA(sequence)
                )
                self.scripts[key] = Script(self.hass, sequence, key, DOMAIN)

    async def async_shutdown(self) -> None:
        self._stopped = True
        if (task := self._power_task) is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for script in self.scripts.values():
            await script.async_unload()
        await super().async_shutdown()

    async def _async_read_power(self) -> Snapshot | None:
        try:
            return await self.client.async_read()
        except CannotConnect:
            return None

    async def async_power(self, on: bool, context: Context | None) -> None:
        """Send a toggle at most once, then confirm actual state under a deadline."""
        if self._stopped or self._power_task is not None:
            raise HomeAssistantError("Power control is stopped or already in progress")
        key = "turn_on_action" if on else "turn_off_action"
        if (on or self.off_mode == "action") and key not in self.scripts:
            raise HomeAssistantError("Configure the power action first")
        if not on and self.off_mode == "disabled":
            raise HomeAssistantError("Power off is disabled")
        self._power_task = asyncio.current_task()
        self.power_transition = "turning_on" if on else "turning_off"
        self.async_update_listeners()
        try:
            async with asyncio.timeout(self.power_timeout):
                state = await self._async_read_power()
                self.async_set_updated_data(state)
                if bool(state and state.screen) == on:
                    return
                if not on and self.off_mode == "adb":
                    try:
                        await self.client.async_turn_off()
                    except CannotConnect:
                        # Power-off can close ADB before its reply. Confirm below.
                        pass
                else:
                    await self.scripts[key].async_run({}, context=context)
                while True:
                    state = await self._async_read_power()
                    self.async_set_updated_data(state)
                    if bool(state and state.screen) == on:
                        return
                    await asyncio.sleep(2)
        except TimeoutError as exc:
            raise HomeAssistantError(
                "Timed out waiting for TV power confirmation"
            ) from exc
        except HaierError as exc:
            self.async_set_update_error(UpdateFailed(str(exc)))
            raise HomeAssistantError(str(exc)) from exc
        finally:
            self._power_task = None
            self.power_transition = None
            self.async_update_listeners()

    async def _async_update_data(self) -> Snapshot | None:
        try:
            return await self.client.async_read()
        except CannotConnect as exc:
            if self.offline_as_off:
                return None
            raise UpdateFailed(str(exc)) from exc
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
