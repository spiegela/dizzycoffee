"""Config flow for the Spinn coffee maker.

Email + password -> ``SpinnClient.login_password``. We store the returned
session **token** (access + refresh) in the entry — never the password. Token
rotation at runtime uses ``auth/token``; a hard failure triggers reauth here.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_DEEP_CLEAN_EVERY,
    CONF_DESCALE_EVERY,
    CONF_DEVICE_NAME,
    CONF_THING_NAME,
    CONF_TOKEN,
    DEFAULT_DEEP_CLEAN_EVERY,
    DEFAULT_DESCALE_EVERY,
    DEFAULT_IOT_BASE,
    DEFAULT_MP_BASE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _login_blocking(email: str, password: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Blocking sign-in + device list. Runs in the executor.

    Returns ``(token_dict, devices)``. Raises on auth / connectivity failure.
    """
    from dizzycoffee.api import SpinnClient  # lazy

    client = SpinnClient(DEFAULT_MP_BASE, DEFAULT_IOT_BASE)
    token = client.login_password(email, password)
    if not token.get("access_token"):
        raise ValueError("no_token")
    devices = client.get_devices()
    return token, devices


class SpinnConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Spinn."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SpinnOptionsFlow:
        return SpinnOptionsFlow()

    def __init__(self) -> None:
        self._email: str | None = None
        self._token: dict[str, Any] | None = None
        self._devices: list[dict[str, Any]] = []
        self._reauth_entry = None

    # --------------------------------------------------------------- user flow
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]
            token, devices, err = await self._try_login(email, password)
            if err:
                errors["base"] = err
            else:
                self._email = email
                self._token = token
                self._devices = devices
                if not devices:
                    return self.async_abort(reason="no_devices")
                if len(devices) == 1:
                    return await self._create_for_device(devices[0])
                return await self.async_step_select_device()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose which machine when the account has more than one."""
        if user_input is not None:
            thing = user_input[CONF_THING_NAME]
            dev = next((d for d in self._devices if d.get("thing_name") == thing), None)
            if dev is not None:
                return await self._create_for_device(dev)

        options = {
            d["thing_name"]: (d.get("name") or d.get("thing_name"))
            for d in self._devices
            if d.get("thing_name")
        }
        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema({vol.Required(CONF_THING_NAME): vol.In(options)}),
        )

    async def _create_for_device(self, device: dict[str, Any]) -> ConfigFlowResult:
        thing = device["thing_name"]
        await self.async_set_unique_id(thing)
        self._abort_if_unique_id_configured()
        name = device.get("name") or f"Spinn {thing}"
        return self.async_create_entry(
            title=name,
            data={
                CONF_EMAIL: self._email,
                CONF_TOKEN: self._token,
                CONF_THING_NAME: thing,
                CONF_DEVICE_NAME: name,
            },
        )

    # ------------------------------------------------------------------ reauth
    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._email = entry_data.get(CONF_EMAIL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and self._reauth_entry is not None:
            email = self._email or user_input.get(CONF_EMAIL)
            password = user_input[CONF_PASSWORD]
            token, _devices, err = await self._try_login(email, password)
            if err:
                errors["base"] = err
            else:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={**self._reauth_entry.data, CONF_EMAIL: email, CONF_TOKEN: token},
                )
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"email": self._email or ""},
            errors=errors,
        )

    # ------------------------------------------------------------------ helper
    async def _try_login(
        self, email: str, password: str
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
        """Return (token, devices, error_key)."""
        try:
            token, devices = await self.hass.async_add_executor_job(
                _login_blocking, email, password
            )
            return token, devices, None
        except ImportError:
            _LOGGER.exception("dizzycoffee library not importable")
            return None, [], "library_missing"
        except Exception as err:  # noqa: BLE001 - map everything to a flow error
            status = getattr(err, "status", None)
            if status in (400, 401, 403):
                return None, [], "invalid_auth"
            _LOGGER.debug("Spinn login failed: %s", err)
            return None, [], "cannot_connect"


def _cups(maximum: int) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0, max=maximum, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="cups"
        )
    )


class SpinnOptionsFlow(OptionsFlow):
    """Maintenance intervals: cups between deep cleans and between descales.

    They drive the Needs attention sensor (deep_clean_due / descale_due), the
    ``interval`` attribute on the cups-since counters, and the machine card's
    maintenance bars. 0 turns a reminder off. Saving needs no reload: the
    entities re-read the options straight away.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={key: int(value) for key, value in user_input.items()}
            )

        # Looked up via the handler (= entry id) rather than self.config_entry,
        # which OptionsFlow only provides from Home Assistant 2024.12.
        entry = self.hass.config_entries.async_get_entry(self.handler)
        options = entry.options if entry else {}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEEP_CLEAN_EVERY,
                        default=options.get(CONF_DEEP_CLEAN_EVERY, DEFAULT_DEEP_CLEAN_EVERY),
                    ): _cups(2000),
                    vol.Required(
                        CONF_DESCALE_EVERY,
                        default=options.get(CONF_DESCALE_EVERY, DEFAULT_DESCALE_EVERY),
                    ): _cups(5000),
                }
            ),
        )
