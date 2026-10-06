"""Buttons: manually switch the video signal of the door station on / off.

"On" keeps a login session open so the camera delivers a real picture instead of
the blue placeholder; "off" tears it down like the app. Neither button sends a
lock request -- they never open the door.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_HOST, CONF_NAME, DEFAULT_NAME, DOMAIN, MANUFACTURER, MODEL, VIDEO_SESSIONS
from .video_session import VideoSession


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    session: VideoSession = hass.data[DOMAIN][VIDEO_SESSIONS][entry.entry_id]
    async_add_entities([
        VideoButton(entry, session, "on"),
        VideoButton(entry, session, "off"),
    ])


class VideoButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, session: VideoSession, kind: str) -> None:
        self._session = session
        self._kind = kind
        self._attr_unique_id = f"{entry.entry_id}_video_{kind}"
        self._attr_name = "Video signal on" if kind == "on" else "Video signal off"
        self._attr_icon = "mdi:video" if kind == "on" else "mdi:video-off"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get(CONF_NAME, DEFAULT_NAME),
            manufacturer=MANUFACTURER,
            model=MODEL,
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )

    async def async_press(self) -> None:
        try:
            if self._kind == "on":
                await self.hass.async_add_executor_job(self._session.start)
            else:
                await self.hass.async_add_executor_job(self._session.stop)
        except PermissionError as err:
            raise HomeAssistantError(f"Login rejected: {err}") from err
        except OSError as err:
            raise HomeAssistantError(f"Device not reachable: {err}") from err
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Video session failed: {err}") from err
