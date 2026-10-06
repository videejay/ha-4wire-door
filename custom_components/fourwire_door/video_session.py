"""Manual "video signal on/off" session for the door station.

Background (verified earlier): the camera sensor of the doorbell only delivers a
real picture while a client session with streamMode=SUB / dataType=MIXED is logged
in on TCP:18600 -- the same path the ControlCam app uses when viewing the camera.
Without such a session the RTSP stream only shows a blue picture.

Design:
  * "on"  = one login (TLV 40+41, exactly like the app / the unlock path) and the
            connection is KEPT OPEN; incoming frames are read and discarded.
  * "off" = the app's teardown packet (TalkRequest action=2) + orderly close.
  * NO lock request is ever sent from here. Nothing in this module opens the door.
  * NO retry / reconnect: if the connection drops, the session simply ends.
  * Safety cap: the session ends by itself after `max_seconds`.
"""
from __future__ import annotations

import logging
import socket
import struct
import threading
import time

from .door_protocol import (
    TLV_LOGIN_RSP,
    _read_one_tlv_frame,
    build_login_packet,
    build_talk_stop_packet,
)

_LOGGER = logging.getLogger(__name__)


class VideoSession:
    """One optional, manually controlled video session (thread based)."""

    def __init__(self, host: str, port: int, user: str, password: str,
                 max_seconds: float, timeout: float = 8.0) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._max_seconds = max_seconds
        self._timeout = timeout
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_active(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    def start(self) -> bool:
        """Blocking. Logs in and keeps the session open in a background thread.
        Returns False if a session is already running (no second one is opened).
        Raises OSError / ValueError / PermissionError on failure."""
        with self._lock:
            if self.is_active:
                return False
            sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
            try:
                sock.sendall(build_login_packet(
                    self._user, self._password, device_id=1, channel_mask=1, sequence=1))
                tlv_type, payload = _read_one_tlv_frame(
                    sock, self._timeout, expect_type=TLV_LOGIN_RSP)
                if tlv_type != TLV_LOGIN_RSP or len(payload) < 2:
                    raise ValueError(f"Unexpected login response (TLV type {tlv_type})")
                (result,) = struct.unpack("<h", payload[0:2])
                if result != 1:
                    raise PermissionError(f"Login failed (result={result})")
            except Exception:
                sock.close()
                raise
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, args=(sock,), name="fourwire_door_video", daemon=True)
            self._thread.start()
            return True

    def stop(self) -> bool:
        """Blocking. Ends a running session cleanly. Returns False if none was active."""
        with self._lock:
            t = self._thread
            if t is None or not t.is_alive():
                return False
            self._stop.set()
        t.join(timeout=self._timeout + 2)
        return True

    def _run(self, sock: socket.socket) -> None:
        deadline = time.monotonic() + self._max_seconds
        try:
            while not self._stop.is_set() and time.monotonic() < deadline:
                sock.settimeout(0.5)
                try:
                    if not sock.recv(65536):
                        _LOGGER.debug("Video session: connection closed by the device")
                        return  # device closed -> session over, no reconnect
                except socket.timeout:
                    continue
            if not self._stop.is_set():
                _LOGGER.info("Video session ended automatically after %.0f s", self._max_seconds)
            # Clean teardown exactly like the app (TalkRequest action=2) + orderly close.
            try:
                sock.sendall(build_talk_stop_packet(2))
                sock.shutdown(socket.SHUT_WR)
                sock.settimeout(1.0)
                while sock.recv(65536):
                    pass
            except OSError:
                pass
        except OSError as err:
            _LOGGER.debug("Video session ended with a socket error: %s", err)
        finally:
            try:
                sock.close()
            except OSError:
                pass
