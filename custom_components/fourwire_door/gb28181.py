"""Minimal GB28181 (SIP over UDP) receiver for doorbell alarms of the door station.

Background (firmware analysis of /usr/fx256, verified live):
  * The door station runs a GB28181-2013 client. Once it is pointed at a "SIP
    server" (web page http://<device>/gb28181.asp), it sends REGISTER, then a
    Keepalive MESSAGE every <heartbeat> seconds (default 60).
  * When someone rings, the indoor station switches the camera on and the
    firmware raises a ~6 s motion alarm. While registered, the device forwards it
    as SIP MESSAGE <CmdType>Alarm</CmdType> with <AlarmMethod>5</AlarmMethod>.
  * A plain "200 OK" to the first REGISTER is accepted (no digest needed). The
    device sets its system clock from the "Date" header of that reply
    (strptime "%Y-%m-%d %H:%M:%S"), so a Date header is ALWAYS sent.

What this module does -- and does not:
  * It only ANSWERS REGISTER and MESSAGE requests from the configured device IP
    with "200 OK". It never sends a request of its own (no INVITE, no query,
    nothing that could open the door).
  * Packets from other IPs are ignored.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

ALARM_METHOD_MOTION = "5"  # how a doorbell ring arrives (camera switched on)


@dataclass
class Gb28181State:
    """Shared state of the receiver, read by the entities."""

    registered_at: float | None = None
    last_keepalive: float | None = None
    last_alarm: float | None = None
    alarms_total: int = 0
    listeners: list[Callable[[], None]] = field(default_factory=list)

    def last_contact(self) -> float | None:
        vals = [v for v in (self.registered_at, self.last_keepalive, self.last_alarm) if v]
        return max(vals) if vals else None

    def notify(self) -> None:
        for cb in list(self.listeners):
            cb()


class OwnActivity:
    """Remembers when THIS integration last had a video session running.

    Such sessions switch the camera on, which raises the same motion alarm as a
    ring. Sessions of the ControlCam app cannot be told apart from a ring.
    """

    def __init__(self) -> None:
        self._last = 0.0
        self.is_active: Callable[[], bool] = lambda: False

    def mark(self) -> None:
        self._last = time.monotonic()

    def recent(self, seconds: float) -> bool:
        return self.is_active() or time.monotonic() - self._last < seconds


def _header(msg: str, name: str) -> str | None:
    m = re.search(r"^" + re.escape(name) + r"\s*:\s*(.*?)\r?$", msg, re.I | re.M)
    return m.group(1).strip() if m else None


def _xml(msg: str, tag: str) -> str | None:
    m = re.search(r"<" + tag + r">(.*?)</" + tag + r">", msg, re.S)
    return m.group(1).strip() if m else None


def build_ok(msg: str) -> bytes | None:
    """200 OK for a REGISTER/MESSAGE request (copies Via/From/To/Call-ID/CSeq)."""
    lines = ["SIP/2.0 200 OK"]
    for via in re.findall(r"^Via\s*:\s*(.*?)\r?$", msg, re.I | re.M):
        lines.append("Via: " + via.strip())
    for name in ("From", "To", "Call-ID", "CSeq"):
        val = _header(msg, name)
        if val is None:
            return None
        if name == "To" and "tag=" not in val:
            val += ";tag=ha%d" % int(time.time())
        lines.append(f"{name}: {val}")
    if msg.startswith("REGISTER"):
        exp = _header(msg, "Expires")
        if exp:
            lines.append("Expires: " + exp)
    # The firmware sets its clock from this (local time, HA time zone).
    lines.append("Date: " + dt_util.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("Content-Length: 0")
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, device_ip: str, state: Gb28181State,
                 on_alarm: Callable[[dict], None]) -> None:
        self._device_ip = device_ip
        self._state = state
        self._on_alarm = on_alarm
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:  # type: ignore[override]
        self._transport = transport

    def datagram_received(self, data: bytes, addr) -> None:  # type: ignore[override]
        if addr[0] != self._device_ip:
            _LOGGER.debug("GB28181: ignoring packet from %s", addr)
            return
        msg = data.decode("utf-8", "replace")
        method = msg.split(" ", 1)[0]
        now = time.time()
        if method == "REGISTER":
            self._state.registered_at = now
            _LOGGER.debug("GB28181: REGISTER from %s", addr)
        elif method == "MESSAGE":
            cmd = _xml(msg, "CmdType")
            if cmd == "Keepalive":
                self._state.last_keepalive = now
            elif cmd == "Alarm":
                self._state.last_alarm = now
                self._state.alarms_total += 1
                info = {
                    "alarm_method": _xml(msg, "AlarmMethod"),
                    "alarm_priority": _xml(msg, "AlarmPriority"),
                    "alarm_time": _xml(msg, "AlarmTime"),
                    "device_id": _xml(msg, "DeviceID"),
                }
                _LOGGER.debug("GB28181: alarm %s", info)
                try:
                    self._on_alarm(info)
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("GB28181: alarm handler failed")
            else:
                _LOGGER.debug("GB28181: MESSAGE %s", cmd)
        else:
            # Responses, INVITE, BYE ...: deliberately not answered.
            _LOGGER.debug("GB28181: not answered: %s", msg.split("\r\n", 1)[0])
            return
        resp = build_ok(msg)
        if resp and self._transport is not None:
            self._transport.sendto(resp, addr)
        self._state.notify()


async def async_start_receiver(
    device_ip: str, port: int, state: Gb28181State, on_alarm: Callable[[dict], None]
) -> asyncio.DatagramTransport:
    """Bind UDP 0.0.0.0:<port> and start answering the device. Raises OSError."""
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _Protocol(device_ip, state, on_alarm),
        local_addr=("0.0.0.0", port),
    )
    _LOGGER.info("GB28181 receiver listening on udp/%d for %s", port, device_ip)
    return transport
