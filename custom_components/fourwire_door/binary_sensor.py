"""Connectivity of the GB28181 doorbell channel.

"On" while the door station is registered and its keepalives arrive. If it turns
"off", the device no longer forwards rings (it drops them silently). Seen live:
after the receiver was unreachable for a longer time the device did not register
again by itself; re-saving the GB28181 page of the device (unchanged values)
brought it back.
"""
from __future__ import annotations

import time
from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_HOST,
    CONF_NAME,
    DEFAULT_NAME,
    DOMAIN,
    GB_STATES,
    GB_STALE_SECONDS,
    MANUFACTURER,
    MODEL,
)
from .gb28181 import Gb28181State


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    state: Gb28181State | None = hass.data[DOMAIN][GB_STATES].get(entry.entry_id)
    if state is not None:
        async_add_entities([DoorbellChannel(entry, state)])


class DoorbellChannel(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "doorbell_channel"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, state: Gb28181State) -> None:
        self._state = state
        self._attr_unique_id = f"{entry.entry_id}_doorbell_channel"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get(CONF_NAME, DEFAULT_NAME),
            manufacturer=MANUFACTURER,
            model=MODEL,
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )

    @property
    def is_on(self) -> bool:
        last = self._state.last_contact()
        return last is not None and time.time() - last < GB_STALE_SECONDS

    @property
    def extra_state_attributes(self) -> dict:
        def fmt(ts: float | None) -> str | None:
            return dt_util.utc_from_timestamp(ts).isoformat() if ts else None

        return {
            "last_register": fmt(self._state.registered_at),
            "last_keepalive": fmt(self._state.last_keepalive),
            "last_alarm": fmt(self._state.last_alarm),
            "alarms_total": self._state.alarms_total,
        }

    async def async_added_to_hass(self) -> None:
        self._state.listeners.append(self._changed)
        self.async_on_remove(lambda: self._state.listeners.remove(self._changed))
        self.async_on_remove(
            async_track_time_interval(self.hass, self._tick, timedelta(seconds=30))
        )

    @callback
    def _tick(self, _now) -> None:
        self.async_write_ha_state()

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()
