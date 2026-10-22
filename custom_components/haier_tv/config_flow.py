"""UI setup, address reconfiguration and ADB authorization retry."""

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector
from homeassistant.helpers.script import async_validate_actions_config

from .api import AuthenticationError, CannotConnect, InvalidResponse, UnsupportedDevice
from .const import DEFAULT_PORT, DOMAIN
from .coordinator import async_create_client


class HaierConfigFlow(ConfigFlow, domain=DOMAIN):
    """Only expose native controls after validating the model and native reads."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HaierOptionsFlow:
        return HaierOptionsFlow()

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


class HaierOptionsFlow(OptionsFlowWithReload):
    """Native HA action sequences for external power control."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                for key in ("turn_on_action", "turn_off_action"):
                    await async_validate_actions_config(
                        self.hass, cv.SCRIPT_SCHEMA(user_input.get(key, []))
                    )
                if user_input["turn_off_mode"] == "action" and not user_input.get(
                    "turn_off_action"
                ):
                    errors["turn_off_action"] = "action_required"
            except vol.Invalid:
                errors["base"] = "invalid_action"
            if not errors:
                return self.async_create_entry(title="", data=user_input)
        defaults = user_input if user_input is not None else self.config_entry.options
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "turn_on_action", default=defaults.get("turn_on_action", [])
                    ): selector.ActionSelector(),
                    vol.Required(
                        "offline_as_off", default=defaults.get("offline_as_off", False)
                    ): selector.BooleanSelector(),
                    vol.Required(
                        "turn_off_mode",
                        default=defaults.get("turn_off_mode", "disabled"),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["disabled", "adb", "action"],
                            translation_key="turn_off_mode",
                        )
                    ),
                    vol.Optional(
                        "turn_off_action", default=defaults.get("turn_off_action", [])
                    ): selector.ActionSelector(),
                    vol.Required(
                        "power_timeout", default=defaults.get("power_timeout", 120)
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=600)),
                }
            ),
        )
