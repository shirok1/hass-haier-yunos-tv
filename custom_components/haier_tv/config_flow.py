"""UI setup, address reconfiguration and ADB authorization retry."""

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import config_validation as cv

from .api import AuthenticationError, CannotConnect, InvalidResponse, UnsupportedDevice
from .const import DEFAULT_PORT, DOMAIN
from .coordinator import async_create_client


class HaierConfigFlow(ConfigFlow, domain=DOMAIN):
    """Only expose native controls after validating the model and native reads."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_configure("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_configure("reconfigure", user_input)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self._async_configure(
                "reauth_confirm", dict(self._get_reauth_entry().data)
            )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=vol.Schema({})
        )

    async def _async_configure(
        self, step: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = (
            self._get_reconfigure_entry()
            if step == "reconfigure"
            else self._get_reauth_entry()
            if step == "reauth_confirm"
            else None
        )
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            data = {CONF_HOST: host, CONF_PORT: port}
            if step == "user":
                self._async_abort_entries_match(data)
            # Do not evict the old adbd's existing HA owner during validation.
            if any(
                e.disabled_by is None and e.data.get(CONF_HOST) == host
                for e in self.hass.config_entries.async_entries("androidtv")
            ):
                errors["base"] = "adb_in_use"
            else:
                client = await async_create_client(
                    self.hass, host, port, entry.unique_id if entry else None
                )
                try:
                    await client.async_read()
                except AuthenticationError:
                    errors["base"] = "auth_failed"
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except UnsupportedDevice:
                    errors["base"] = "unsupported_device"
                except InvalidResponse:
                    errors["base"] = "invalid_response"
                finally:
                    await client.async_close()
                if not errors:
                    assert client.info is not None
                    await self.async_set_unique_id(client.info.unique_id)
                    if entry:
                        self._abort_if_unique_id_mismatch()
                        return self.async_update_reload_and_abort(
                            entry, data_updates=data
                        )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title=client.info.model, data=data)
        defaults = user_input or (dict(entry.data) if entry else {})
        schema = (
            vol.Schema({})
            if step == "reauth_confirm"
            else vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=defaults.get(CONF_HOST, "")
                    ): cv.string,
                    vol.Required(
                        CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
                    ): cv.port,
                }
            )
        )
        return self.async_show_form(step_id=step, data_schema=schema, errors=errors)
