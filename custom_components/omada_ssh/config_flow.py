"""Config flow for the Omada ER605 (SSH) integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import callback
import voluptuous as vol

from .client import OmadaAuthError, OmadaError, OmadaSSHClient
from .const import (
    CONF_CONSIDER_HOME,
    CONF_PING_TARGET,
    DEFAULT_CONSIDER_HOME,
    DEFAULT_HOST,
    DEFAULT_PING_TARGET,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USERNAME,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .parsers import SystemInfo

_LOGGER = logging.getLogger(__name__)


async def _async_validate(data: Mapping[str, Any]) -> SystemInfo:
    client = OmadaSSHClient(
        data[CONF_HOST], data[CONF_PORT], data[CONF_USERNAME], data[CONF_PASSWORD]
    )
    try:
        return await client.async_get_system_info()
    finally:
        await client.async_close()


def _errors_for(err: Exception) -> dict[str, str]:
    if isinstance(err, OmadaAuthError):
        return {"base": "invalid_auth"}
    if isinstance(err, OmadaError):
        return {"base": "cannot_connect"}
    _LOGGER.exception("Unexpected error")
    return {"base": "unknown"}


class OmadaSSHConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the router address and credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await _async_validate(user_input)
            except Exception as err:
                errors = _errors_for(err)
            else:
                await self.async_set_unique_id(info.mac or user_input[CONF_HOST])
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: user_input[CONF_HOST]}
                )
                return self.async_create_entry(
                    title=info.name or user_input[CONF_HOST], data=user_input
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start a reauthentication after the password was refused."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new credentials."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            try:
                await _async_validate(data)
            except Exception as err:
                errors = _errors_for(err)
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OmadaSSHOptionsFlow:
        """Return the options flow."""
        return OmadaSSHOptionsFlow()


class OmadaSSHOptionsFlow(OptionsFlow):
    """Polling interval, away delay and ping target."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            user_input[CONF_PING_TARGET] = user_input.get(CONF_PING_TARGET, "").strip()
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)),
                    vol.Required(
                        CONF_CONSIDER_HOME,
                        default=options.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0)),
                    vol.Optional(
                        CONF_PING_TARGET,
                        description={
                            "suggested_value": options.get(
                                CONF_PING_TARGET, DEFAULT_PING_TARGET
                            )
                        },
                    ): str,
                }
            ),
        )
