"""Lock entity: deliberate manual door opening with PIN prompt.

Design:
  * is_locked is ALWAYS True -- there is no real door-status channel, so "open" is
    never faked. The open command is a momentary action.
  * On opening, the UI asks for a PIN (code_format). The PIN is checked locally
    against the stored password (lockout-safe, like the original app) and sent as
    lockPwd to the device; the device validates it additionally.
  * No automation, no retry -- one button press = one transaction.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import ATTR_CODE, LockEntity, LockEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
    CONF_USERNAME,
    CONF_VIDEO_WAIT_TIMEOUT,
    DEFAULT_ACTION,
    DEFAULT_CHANNEL,
    DEFAULT_LINGER_SECONDS,
    DEFAULT_LOCKDELAY,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_VIDEO_WAIT_TIMEOUT,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    PIN_CODE_FORMAT,
)
from .door_protocol import unlock_once

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([FourWireDoorLock(entry)])


class FourWireDoorLock(LockEntity):
    """Momentary door opener as a lock entity with PIN prompt."""

    _attr_has_entity_name = True
    _attr_name = None  # uses the device name
    _attr_supported_features = LockEntityFeature.OPEN

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_lock"
        self._attr_is_locked = True
        self._attr_is_unlocking = False
        name = entry.data.get(CONF_NAME, DEFAULT_NAME)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )
        # Only ask for a PIN if desired (default: yes)
        if entry.options.get(CONF_REQUIRE_PIN, True):
            self._attr_code_format = PIN_CODE_FORMAT

    @property
    def _require_pin(self) -> bool:
        return self._entry.options.get(CONF_REQUIRE_PIN, True)

    async def async_unlock(self, **kwargs: Any) -> None:
        """Called by HA (unlock/open). Opens the door ONCE."""
        await self._do_open(kwargs.get(ATTR_CODE))

    async def async_open(self, **kwargs: Any) -> None:
        """Latch/open action -- same effect as unlock on this device."""
        await self._do_open(kwargs.get(ATTR_CODE))

    async def async_lock(self, **kwargs: Any) -> None:
        """No real locking possible -- the entity is considered locked anyway."""
        self._attr_is_locked = True
        self.async_write_ha_state()

    async def _do_open(self, code: str | None) -> None:
        data = self._entry.data
        opts = self._entry.options
        password = data[CONF_PASSWORD]

        if self._require_pin:
            if not code:
                raise HomeAssistantError("PIN required to open the door.")
            # Local check (lockout-safe, like the original app): on this device the
            # PIN is identical to the device password.
            if code != password:
                raise HomeAssistantError("Wrong PIN - the door will not be opened.")
            lock_pwd = code
        else:
            lock_pwd = password

        self._attr_is_unlocking = True
        self.async_write_ha_state()
        try:
            ok = await self.hass.async_add_executor_job(
                _run_unlock, data, opts, lock_pwd
            )
        except PermissionError as err:
            raise HomeAssistantError(f"Login/PIN rejected: {err}") from err
        except OSError as err:
            raise HomeAssistantError(f"Device not reachable: {err}") from err
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Door opening failed: {err}") from err
        finally:
            self._attr_is_unlocking = False
            self._attr_is_locked = True
            self.async_write_ha_state()

        if not ok:
            raise HomeAssistantError(
                "Device did not confirm the opening (result != 1)."
            )
        _LOGGER.info("Door opening confirmed (protocol success result=1).")


def _run_unlock(data: dict, opts: dict, lock_pwd: str) -> bool:
    """Blocking call -- runs in the executor."""
    return unlock_once(
        host=data[CONF_HOST],
        port=int(data.get(CONF_PORT, DEFAULT_PORT)),
        user=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        lock_pwd=lock_pwd,
        channel=int(opts.get(CONF_CHANNEL, DEFAULT_CHANNEL)),
        action=int(opts.get(CONF_ACTION, DEFAULT_ACTION)),
        lockdelay=int(opts.get(CONF_LOCKDELAY, DEFAULT_LOCKDELAY)),
        video_wait_timeout=float(
            opts.get(CONF_VIDEO_WAIT_TIMEOUT, DEFAULT_VIDEO_WAIT_TIMEOUT)
        ),
        linger_seconds=float(opts.get(CONF_LINGER_SECONDS, DEFAULT_LINGER_SECONDS)),
    )
