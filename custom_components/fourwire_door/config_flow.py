"""Config- und Options-Flow fuer die 4-Wire-Door-Integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_ACTION,
    CONF_CHANNEL,
    CONF_HOST,
    CONF_LINGER_SECONDS,
    CONF_LOCKDELAY,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_REQUIRE_PIN,
    CONF_RTSP_PATH,
    CONF_USERNAME,
    CONF_VIDEO_WAIT_TIMEOUT,
    DEFAULT_ACTION,
    DEFAULT_CHANNEL,
    DEFAULT_LINGER_SECONDS,
    DEFAULT_LOCKDELAY,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_RTSP_PATH,
    DEFAULT_VIDEO_WAIT_TIMEOUT,
    DOMAIN,
)
from .door_protocol import probe_login

_LOGGER = logging.getLogger(__name__)


async def _validate(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Prüft Erreichbarkeit + Login (ohne Türöffnung). Throw bei Fehler."""
    await hass.async_add_executor_job(
        probe_login,
        data[CONF_HOST],
        int(data.get(CONF_PORT, DEFAULT_PORT)),
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
    )


class FourWireDoorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Führt den Nutzer durch das Anlegen eines Geräts."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_HOST]}:{user_input.get(CONF_PORT, DEFAULT_PORT)}"
            )
            self._abort_if_unique_id_configured()
            try:
                await _validate(self.hass, user_input)
            except PermissionError:
                errors["base"] = "invalid_auth"
            except OSError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unerwarteter Fehler bei der Validierung")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME) or DEFAULT_NAME,
                    data={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: int(user_input.get(CONF_PORT, DEFAULT_PORT)),
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_NAME: user_input.get(CONF_NAME) or DEFAULT_NAME,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "FourWireDoorOptionsFlow":
        return FourWireDoorOptionsFlow(config_entry)


class FourWireDoorOptionsFlow(config_entries.OptionsFlow):
    """Feineinstellungen (optional)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self._entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_REQUIRE_PIN,
                    default=opts.get(CONF_REQUIRE_PIN, True),
                ): bool,
                vol.Optional(
                    CONF_RTSP_PATH,
                    default=opts.get(CONF_RTSP_PATH, DEFAULT_RTSP_PATH),
                ): str,
                vol.Optional(
                    CONF_VIDEO_WAIT_TIMEOUT,
                    default=opts.get(
                        CONF_VIDEO_WAIT_TIMEOUT, DEFAULT_VIDEO_WAIT_TIMEOUT
                    ),
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_LINGER_SECONDS,
                    default=opts.get(CONF_LINGER_SECONDS, DEFAULT_LINGER_SECONDS),
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_CHANNEL,
                    default=opts.get(CONF_CHANNEL, DEFAULT_CHANNEL),
                ): int,
                vol.Optional(
                    CONF_ACTION,
                    default=opts.get(CONF_ACTION, DEFAULT_ACTION),
                ): int,
                vol.Optional(
                    CONF_LOCKDELAY,
                    default=opts.get(CONF_LOCKDELAY, DEFAULT_LOCKDELAY),
                ): int,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
