"""Lock-Entität: bewusste manuelle Türöffnung mit PIN-Abfrage.

Design:
  * is_locked ist IMMER True -- es gibt keinen echten Türstatus-Kanal, also wird
    kein "offen" vorgetäuscht. Der Öffnungsbefehl ist eine momentane Aktion.
  * Die UI fragt beim Öffnen eine PIN ab (code_format). Die PIN wird lokal gegen
    das hinterlegte Passwort geprueft (lockout-sicher, wie die Original-App) und als
    lockPwd an das Geraet gesendet; das Gerät validiert zusätzlich.
  * Keine Automatik, kein Retry -- ein Tastendruck = eine Transaktion.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import ATTR_CODE, LockEntity, LockEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_info import DeviceInfo
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
    """Momentaner Türöffner als Lock-Entitaet mit PIN-Abfrage."""

    _attr_has_entity_name = True
    _attr_name = None  # nutzt den Geraetenamen
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
        # PIN nur abfragen, wenn gewünscht (Default: ja)
        if entry.options.get(CONF_REQUIRE_PIN, True):
            self._attr_code_format = PIN_CODE_FORMAT

    @property
    def _require_pin(self) -> bool:
        return self._entry.options.get(CONF_REQUIRE_PIN, True)

    async def async_unlock(self, **kwargs: Any) -> None:
        """Von HA aufgerufen (Unlock/Open). Öffnet die Tür EINMALIG."""
        await self._do_open(kwargs.get(ATTR_CODE))

    async def async_open(self, **kwargs: Any) -> None:
        """Latch/Open-Aktion -- gleiche Wirkung wie Unlock bei diesem Gerät."""
        await self._do_open(kwargs.get(ATTR_CODE))

    async def async_lock(self, **kwargs: Any) -> None:
        """Kein echtes Verriegeln moeglich -- Entität gilt ohnehin als verriegelt."""
        self._attr_is_locked = True
        self.async_write_ha_state()

    async def _do_open(self, code: str | None) -> None:
        data = self._entry.data
        opts = self._entry.options
        password = data[CONF_PASSWORD]

        if self._require_pin:
            if not code:
                raise HomeAssistantError("PIN erforderlich, um die Tür zu öffnen.")
            # Lokale Pruefung (lockout-sicher, wie die Original-App): die PIN ist bei
            # diesem Geraet identisch mit dem Geraete-Passwort.
            if code != password:
                raise HomeAssistantError("Falsche PIN – Tür wird nicht geöffnet.")
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
            raise HomeAssistantError(f"Login/PIN abgelehnt: {err}") from err
        except OSError as err:
            raise HomeAssistantError(f"Gerät nicht erreichbar: {err}") from err
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Türöffnung fehlgeschlagen: {err}") from err
        finally:
            self._attr_is_unlocking = False
            self._attr_is_locked = True
            self.async_write_ha_state()

        if not ok:
            raise HomeAssistantError(
                "Gerät hat die Öffnung nicht bestätigt (result != 1)."
            )
        _LOGGER.info("Türöffnung bestätigt (Protokoll-Erfolg result=1).")


def _run_unlock(data: dict, opts: dict, lock_pwd: str) -> bool:
    """Blockierender Aufruf -- laeuft im Executor."""
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
