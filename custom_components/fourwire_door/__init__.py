"""4-Wire Door integration (GBF MR263C4 / ControlCam).

Local, manual door opening + RTSP stream + manual video on/off
+ doorbell event via the device's GB28181 (SIP) alarm push.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_GB_ENABLED,
    CONF_GB_PORT,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    DEFAULT_GB_ENABLED,
    DEFAULT_GB_PORT,
    DEFAULT_PORT,
    DOMAIN,
    EVENT_RING,
    GB_STATES,
    OWN_ACTIVITY,
    OWN_ACTIVITY_SUPPRESS_SECONDS,
    SIGNAL_RING,
    VIDEO_SESSION_MAX_SECONDS,
    VIDEO_SESSIONS,
)
from .gb28181 import ALARM_METHOD_MOTION, Gb28181State, OwnActivity, async_start_receiver
from .video_session import VideoSession

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.LOCK,
    Platform.CAMERA,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a device from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data[entry.entry_id] = entry
    session = VideoSession(
        host=entry.data[CONF_HOST],
        port=int(entry.data.get(CONF_PORT, DEFAULT_PORT)),
        user=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        max_seconds=VIDEO_SESSION_MAX_SECONDS,
    )
    domain_data.setdefault(VIDEO_SESSIONS, {})[entry.entry_id] = session
    own = OwnActivity()
    own.is_active = lambda: session.is_active
    domain_data.setdefault(OWN_ACTIVITY, {})[entry.entry_id] = own

    gb_states = domain_data.setdefault(GB_STATES, {})
    if entry.options.get(CONF_GB_ENABLED, DEFAULT_GB_ENABLED):
        state = Gb28181State()
        gb_states[entry.entry_id] = state

        @callback
        def _on_alarm(info: dict) -> None:
            if info.get("alarm_method") != ALARM_METHOD_MOTION:
                _LOGGER.debug("GB28181 alarm ignored (method %s)", info.get("alarm_method"))
                return
            if own.recent(OWN_ACTIVITY_SUPPRESS_SECONDS):
                _LOGGER.debug("GB28181 alarm during own video session - not a ring")
                return
            data = {"entry_id": entry.entry_id, **info}
            hass.bus.async_fire(EVENT_RING, data)
            async_dispatcher_send(hass, SIGNAL_RING.format(entry.entry_id), info)

        port = int(entry.options.get(CONF_GB_PORT, DEFAULT_GB_PORT))
        try:
            transport = await async_start_receiver(
                entry.data[CONF_HOST], port, state, _on_alarm
            )
        except OSError as err:
            _LOGGER.error("GB28181 receiver could not bind udp/%d: %s", port, err)
        else:
            entry.async_on_unload(transport.close)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a device again."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        session = hass.data[DOMAIN][VIDEO_SESSIONS].pop(entry.entry_id, None)
        if session is not None:
            # End a running video session cleanly (teardown like the app).
            await hass.async_add_executor_job(session.stop)
        hass.data[DOMAIN].get(GB_STATES, {}).pop(entry.entry_id, None)
        hass.data[DOMAIN].get(OWN_ACTIVITY, {}).pop(entry.entry_id, None)
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the device when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
