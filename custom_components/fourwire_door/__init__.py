"""4-Wire Door integration (GBF MR263C4 / ControlCam).

Local, manual door opening + RTSP stream + manual video on/off.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    DEFAULT_PORT,
    DOMAIN,
    VIDEO_SESSION_MAX_SECONDS,
    VIDEO_SESSIONS,
)
from .video_session import VideoSession

PLATFORMS: list[Platform] = [Platform.LOCK, Platform.CAMERA, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a device from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data[entry.entry_id] = entry
    domain_data.setdefault(VIDEO_SESSIONS, {})[entry.entry_id] = VideoSession(
        host=entry.data[CONF_HOST],
        port=int(entry.data.get(CONF_PORT, DEFAULT_PORT)),
        user=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        max_seconds=VIDEO_SESSION_MAX_SECONDS,
    )
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
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the device when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
