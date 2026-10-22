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
    """Edit power actions and state handling independently without losing options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["power_on", "power_off", "power_state"]
        )

    async def async_step_power_on(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_action_step("power_on", "turn_on_action", user_input)

    async def async_step_power_off(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            if user_input["turn_off_mode"] == "action":
                return await self.async_step_power_off_action()
            return self.async_create_entry(
                title="", data=dict(self.config_entry.options) | user_input
            )
        return self.async_show_form(
            step_id="power_off",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "turn_off_mode",
                        default=self.config_entry.options.get(
                            "turn_off_mode", "disabled"
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["disabled", "adb", "action"],
                            translation_key="turn_off_mode",
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_power_off_action(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_action_step(
            "power_off_action", "turn_off_action", user_input
        )

    async def _async_action_step(
        self, step: str, key: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            sequence = user_input.get(key, [])
            try:
                await async_validate_actions_config(
                    self.hass, cv.SCRIPT_SCHEMA(sequence)
                )
            except vol.Invalid:
                errors[key] = "invalid_action"
            if key == "turn_off_action" and not sequence:
                errors[key] = "action_required"
            if not errors:
                data = dict(self.config_entry.options) | {key: sequence}
                if key == "turn_off_action":
                    data["turn_off_mode"] = "action"
                return self.async_create_entry(title="", data=data)
        defaults = user_input if user_input is not None else self.config_entry.options
        return self.async_show_form(
            step_id=step,
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        key, default=defaults.get(key, [])
                    ): selector.ActionSelector(),
                }
            ),
        )

    async def async_step_power_state(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="", data=dict(self.config_entry.options) | user_input
            )
        defaults = self.config_entry.options
        return self.async_show_form(
            step_id="power_state",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "offline_as_off", default=defaults.get("offline_as_off", False)
                    ): selector.BooleanSelector(),
                    vol.Required(
                        "power_timeout", default=defaults.get("power_timeout", 120)
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=10,
                            max=600,
                            step=1,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
