"""Config and options flow for Viessmann CN."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    ViessmannApi,
    ViessmannApiError,
    ViessmannAuthError,
    ViessmannConnectionError,
    ViessmannError,
)
from .const import (
    API_BASE_URL,
    CONF_BASE_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)


class ViessmannConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the 菲斯曼互联 phone number and password."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                user_id = await _async_validate(self.hass, user_input)
            except ViessmannAuthError:
                errors["base"] = "invalid_auth"
            except ViessmannConnectionError:
                errors["base"] = "cannot_connect"
            except ViessmannApiError as err:
                _LOGGER.error("Viessmann CN setup failed: %s", err)
                errors["base"] = "api_error"
            except NoDevices:
                errors["base"] = "no_devices"
            except Exception:  # noqa: BLE001 - surface anything else as unknown
                _LOGGER.exception("Unexpected error during config flow")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(f"user_{user_id}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"菲斯曼互联 {user_input[CONF_USERNAME]}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None
        if user_input is not None:
            data = {CONF_USERNAME: entry.data[CONF_USERNAME], **user_input}
            try:
                await _async_validate(self.hass, data, base_url=entry.data.get(CONF_BASE_URL))
            except ViessmannAuthError:
                errors["base"] = "invalid_auth"
            except ViessmannConnectionError:
                errors["base"] = "cannot_connect"
            except ViessmannApiError as err:
                _LOGGER.error("Viessmann CN reauth failed: %s", err)
                errors["base"] = "api_error"
            except NoDevices:
                errors["base"] = "api_error"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during reauth")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    )
                }
            ),
            description_placeholders={CONF_USERNAME: entry.data[CONF_USERNAME]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ViessmannOptionsFlow()


class ViessmannOptionsFlow(OptionsFlow):
    """Polling interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    )
                }
            ),
        )


class NoDevices(Exception):
    """The account is valid but has no boiler bound."""


async def _async_validate(
    hass: HomeAssistant, data: dict[str, Any], base_url: str | None = None
) -> str:
    """Log in and make sure the account actually has a boiler."""
    session = async_get_clientsession(hass)
    api = ViessmannApi(
        session,
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        base_url or data.get(CONF_BASE_URL) or API_BASE_URL,
    )
    await api.async_get_token()
    info: dict[str, Any] = {}
    try:
        info = await api.async_get_user_info()
    except ViessmannError as err:
        # The token from the login response is enough to continue; user/info
        # is only used to learn the user id.
        _LOGGER.warning("user/info failed: %s", err)
    user_id = api.user_id or info.get("userId") or data[CONF_USERNAME]
    devices = await api.async_get_devices(refresh=True)
    if not devices:
        raise NoDevices
    _LOGGER.debug("Account %s has %d boiler(s)", user_id, len(devices))
    return str(user_id)
