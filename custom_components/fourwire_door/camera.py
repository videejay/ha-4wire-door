"""Kamera-Entität: RTSP-Live-Stream der Türstation.

Stream-Pfad fuer dieses Geraet: rtsp://<host>/tcp/av1_0
(ueber Options-Flow anpassbar). Nutzt das in HA eingebaute ffmpeg/stream-Backend.
"""
from __future__ import annotations

from homeassistant.components import ffmpeg
from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_info import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_HOST,
    CONF_NAME,
    CONF_RTSP_PATH,
    DEFAULT_NAME,
    DEFAULT_RTSP_PATH,
    DOMAIN,
    MANUFACTURER,
    MODEL,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([FourWireDoorCamera(hass, entry)])


class FourWireDoorCamera(Camera):
    """RTSP-Stream der Türstation."""

    _attr_has_entity_name = True
    _attr_name = "Live"
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__()
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_camera"
        host = entry.data[CONF_HOST]
        path = entry.options.get(CONF_RTSP_PATH, DEFAULT_RTSP_PATH)
        if not path.startswith("/"):
            path = "/" + path
        self._stream_url = f"rtsp://{host}{path}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get(CONF_NAME, DEFAULT_NAME),
            manufacturer=MANUFACTURER,
            model=MODEL,
            configuration_url=f"http://{host}",
        )

    async def stream_source(self) -> str | None:
        return self._stream_url

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Standbild per ffmpeg aus dem RTSP-Stream greifen."""
        return await ffmpeg.async_get_image(
            self.hass, self._stream_url, width=width, height=height
        )
