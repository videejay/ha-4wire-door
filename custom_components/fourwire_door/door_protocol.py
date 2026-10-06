#!/usr/bin/env python3
"""
GBF MR263C4 / ControlCam -- manual single action "open door".

IMPORTANT -- please read before use:
  * Every call of this script is ONE network transaction (one TLV_T_LOCK_REQ).
    There is NO retry logic and NO automatic polling. Do not wire it into an
    automation: -- only trigger it manually via script:/shell_command: or a
    dashboard button operated by a person.
  * A "success" only means: the device answered with TLV_T_LOCK_RSP result=1
    (protocol acknowledgement). This is NOT independent proof that the door is
    actually open -- there is no separate door-status channel. Do not display it
    as a door status in Home Assistant.
  * Passwords/secrets are never logged or written to stdout.

Protocol quick reference (see report for details and source references):
  OwspPacketHeader (8 bytes): packet_length (4B, BIG-ENDIAN) + packet_seq (4B, LITTLE-ENDIAN)
  TLV_HEADER       (4 bytes): tlv_type (2B LE) + tlv_len (2B LE)
  Login request  (TLV 40 Version + TLV 41 Login, TLV_V_LoginRequestEx, 68 bytes)
  Login response (TLV 42, 4 bytes: result (2B LE) + reserve (2B LE))
  Lock request   (TLV 425, _TLV_V_Lock_Req, 42 bytes:
                  deviceId(4B LE) + lockPwd(32B, null-term. ASCII) +
                  lockdelay(2B LE) + channel(1B) + action(1B) + reserve(2B))
  Lock response  (TLV 426, 4 bytes: result (2B LE) + reserve (2B LE))
"""

import argparse
import socket
import struct
import sys
import time

TLV_VERSION = 40
TLV_LOGIN_REQ = 41
TLV_LOGIN_RSP = 42
TLV_TALK_REQ = 331   # sent by the app in closeImpl() as a teardown with action=2
TLV_LOCK_REQ = 425
TLV_LOCK_RSP = 426

OWSP_HEADER_LEN = 8
TLV_HEADER_LEN = 4


def _tlv_header(tlv_type: int, tlv_len: int) -> bytes:
    # tlv_type, tlv_len: both 2 bytes LITTLE-ENDIAN (see MyUtil.ChangeByteOrder analysis)
    return struct.pack("<HH", tlv_type, tlv_len)


def _owsp_header(packet_length: int, packet_seq: int) -> bytes:
    # packet_length: 4 bytes BIG-ENDIAN; packet_seq: 4 bytes LITTLE-ENDIAN
    return struct.pack(">I", packet_length) + struct.pack("<I", packet_seq)


def _pad(s: str, length: int) -> bytes:
    b = s.encode("ascii", errors="strict")
    if len(b) >= length:
        raise ValueError(f"Value too long for field size {length}: length {len(b)}")
    return b + b"\x00" * (length - len(b))


#   OWSP_StreamType (com/goolink/comm/OWSP_StreamType.java): MAIN=0, SUB=1, VOD=2, MODE_SETTING=3
#   OWSP_StreamDataType (com/goolink/comm/OWSP_StreamDataType.java): VIDEO=0, AUDIO=1, MIXED=2
# MainActivity2.onSelectCamera() -- the regular "tap/view camera" path that, in the
# real app, leads to a successful door opening -- calls
# requestSource(..., OWSP_STREAM_SUB, OWSP_MIXED_DATA, ...). A login with
# streamMode=MAIN(0)/dataType=VIDEO(0) did return TLV-100/101 packets, but the door
# did NOT open and the parallel RTSP stream stayed blue -- hence SUB/MIXED is now the
# default, to reproduce the real app path.
STREAM_MODE_SUB = 1
DATA_TYPE_MIXED = 2


def build_login_packet(user: str, password: str, device_id: int, channel_mask: int, sequence: int,
                        stream_mode: int = STREAM_MODE_SUB, data_type: int = DATA_TYPE_MIXED) -> bytes:
    # TLV 40: Version (4 bytes: versionMajor, versionMinor, 2 bytes LE each)
    version_payload = struct.pack("<HH", 5, 0)
    version_block = _tlv_header(TLV_VERSION, len(version_payload)) + version_payload

    # TLV 41: Login (68 bytes, see TLV_V_LoginRequestEx.java)
    login_payload = b"".join([
        bytes([0]),                 # encryptType
        _pad(user, 32),             # userName
        _pad(password, 16),         # password
        struct.pack("<i", device_id),   # deviceId, LE
        struct.pack("<i", 2),           # flag = 2 (fixed, as in the app)
        b"\x00\x00\x00",                # reserve3
        struct.pack("<I", channel_mask)[:4],  # channelMask (lower 4 bytes, LE)
        bytes([stream_mode]),       # streamMode -- now SUB(1) instead of MAIN(0), see above
        bytes([data_type]),         # dataType -- now MIXED(2) instead of VIDEO(0), see above
        bytes([0, 0]),               # reserve, reserve2
    ])
    assert len(login_payload) == 68, f"Login payload length wrong: {len(login_payload)}"
    login_block = _tlv_header(TLV_LOGIN_REQ, len(login_payload)) + login_payload

    content = version_block + login_block
    packet_length = len(content) + 4  # see parser logic: total = content_len + 4
    return _owsp_header(packet_length, sequence) + content


def build_lock_packet(password: str, channel: int, action: int, lockdelay: int, sequence: int) -> bytes:
    lock_payload = b"".join([
        struct.pack("<i", 0),        # deviceId = 0 (hard-coded, as in the app)
        _pad(password, 32),          # lockPwd = device/login password
        struct.pack("<H", lockdelay),# lockdelay, LE
        bytes([channel]),            # channel
        bytes([action]),             # action (1 = from observed real transaction)
        b"\x00\x00",                  # reserve
    ])
    assert len(lock_payload) == 42, f"Lock payload length wrong: {len(lock_payload)}"
    lock_block = _tlv_header(TLV_LOCK_REQ, len(lock_payload)) + lock_payload

    packet_length = len(lock_block) + 4
    return _owsp_header(packet_length, sequence) + lock_block


def build_talk_stop_packet(sequence: int) -> bytes:
    """Reproduces EXACTLY the teardown packet that the app sends in
    EyeSourceTransNet.closeImpl() before closing:
    TalkRequestReqPack(deviceId=0, action=2). Struct TLV_V_TalkRequest (8 bytes):
    deviceId(4B LE) + action(1B) + reserve(3B). Its purpose is to cleanly reset the
    device/doorbell state (presumably SS_VI_DOORBELL_CONTROL_SET(0)), so that the
    next video open is a fresh transition again -- otherwise only the first attempt
    opens the door."""
    talk_payload = b"".join([
        struct.pack("<i", 0),   # deviceId = 0
        bytes([2]),             # action = 2 (stop/teardown, as in closeImpl())
        b"\x00\x00\x00",        # reserve[3]
    ])
    assert len(talk_payload) == 8, f"Talk payload length wrong: {len(talk_payload)}"
    talk_block = _tlv_header(TLV_TALK_REQ, len(talk_payload)) + talk_payload
    packet_length = len(talk_block) + 4
    return _owsp_header(packet_length, sequence) + talk_block


def _recv_exact(sock: socket.socket, n: int, timeout: float) -> bytes:
    sock.settimeout(timeout)
    buf = b""
    deadline = time.monotonic() + timeout
    while len(buf) < n:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Timeout while reading ({len(buf)}/{n} bytes received)")
        sock.settimeout(remaining)
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed by the device")
        buf += chunk
    return buf


def _read_one_owsp_packet(sock: socket.socket, timeout: float):
    """Reads exactly one OwspPacketHeader + content and splits it into all contained
    TLV blocks (one packet can contain several blocks, e.g. TLV 40 + TLV 42 in the
    login response)."""
    owsp_raw = _recv_exact(sock, OWSP_HEADER_LEN, timeout)
    (packet_length,) = struct.unpack(">I", owsp_raw[0:4])
    content_len = packet_length - 4
    if content_len <= 0 or content_len > 1_000_000:
        raise ValueError(f"Implausible packet_length from the device: {packet_length}")
    content = _recv_exact(sock, content_len, timeout)

    blocks = []
    off = 0
    while off + 4 <= len(content):
        tlv_type, tlv_len = struct.unpack("<HH", content[off:off + 4])
        payload = content[off + 4:off + 4 + tlv_len]
        blocks.append((tlv_type, payload))
        off += 4 + tlv_len
        if tlv_len == 0:
            break
    if not blocks:
        raise ValueError("Empty TLV content from the device")
    return blocks


def _read_one_tlv_frame(sock: socket.socket, timeout: float, expect_type: int = None):
    """Reads OwspPacketHeader+content, across MULTIPLE consecutive packets if needed,
    until a block of type expect_type is found. This is necessary because after the
    login, video frame packets (TLV 99/100/101) can keep coming in before e.g. the
    lock response (TLV 426) arrives. Without expect_type, simply the first block of
    the first packet is returned (legacy behavior). Raises TimeoutError if expect_type
    does not appear within timeout."""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"TLV type {expect_type} not received within {timeout}s "
                f"(probably only video frame packets in between)")
        blocks = _read_one_owsp_packet(sock, remaining)
        if expect_type is None:
            return blocks[0]
        for tlv_type, payload in blocks:
            if tlv_type == expect_type:
                return tlv_type, payload
        # No matching block in this packet (e.g. pure video frame packets) --
        # read the next packet until expect_type arrives or the time limit is hit.


TLV_VIDEO_IFRAME_DATA = 100


def _wait_for_video_active(sock: socket.socket, timeout: float, min_iframes: int = 3,
                            settle_seconds: float = 1.0, verbose: bool = False) -> bool:
    """Keeps reading from the socket after the login until MULTIPLE real I-frames
    (TLV 100) have been received, plus a short settle time -- or until timeout
    expires.

    Background: the firmware apparently triggers the physical door-opener output on
    the lock command only when the video channel is REALLY active. Right after the
    login the device starts pushing frames on its own -- but the camera sensor of a
    doorbell needs a varying wake-up time, and the first "I-frames" may still be blue
    placeholders. Therefore, do not proceed immediately after the FIRST I-frame, but
    wait for several I-frames (min_iframes) and then buffer another settle_seconds, so
    that the sensor is reliably running for real.
    Returns True if enough I-frames were seen, otherwise False (processing continues
    anyway, but with a warning)."""
    buf = b""
    iframes = 0
    deadline = time.monotonic() + timeout
    settle_until = None
    while time.monotonic() < deadline:
        if settle_until is not None and time.monotonic() >= settle_until:
            if verbose:
                print(f"{iframes} I-frames + settle time reached -- sending lock now.", file=sys.stderr)
            return True
        remaining = deadline - time.monotonic()
        sock.settimeout(max(0.1, min(remaining, 0.5)))
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            continue
        if not chunk:
            break
        buf += chunk
        while len(buf) >= OWSP_HEADER_LEN:
            (packet_length,) = struct.unpack(">I", buf[0:4])
            total = packet_length + 4
            if total <= OWSP_HEADER_LEN or total > 2_000_000 or len(buf) < total:
                break
            content = buf[8:total]
            off = 0
            while off + 4 <= len(content):
                tlv_type, tlv_len = struct.unpack("<HH", content[off:off + 4])
                if tlv_type == TLV_VIDEO_IFRAME_DATA:
                    iframes += 1
                    if iframes >= min_iframes and settle_until is None:
                        settle_until = time.monotonic() + settle_seconds
                        if verbose:
                            print(f"I-frame #{iframes} -- waiting another {settle_seconds}s settle time.",
                                  file=sys.stderr)
                off += 4 + tlv_len
                if tlv_len == 0:
                    break
            buf = buf[total:]
    if verbose:
        print(f"Only {iframes} I-frame(s) within the timeout -- proceeding anyway.",
              file=sys.stderr)
    return iframes > 0


def probe_login(host: str, port: int, user: str, password: str,
                timeout: float = 6.0) -> None:
    """Checks ONLY connection + login (NO lock, NO door opening). For the HA config
    flow, to validate credentials/reachability.
    Raises on connection error (OSError), on protocol error (ValueError), or on
    wrong login (PermissionError)."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        login_pkt = build_login_packet(user, password, device_id=1, channel_mask=1, sequence=1)
        sock.sendall(login_pkt)
        tlv_type, payload = _read_one_tlv_frame(sock, timeout, expect_type=TLV_LOGIN_RSP)
        if tlv_type != TLV_LOGIN_RSP or len(payload) < 2:
            raise ValueError(f"Unexpected login response (TLV type {tlv_type})")
        (login_result,) = struct.unpack("<h", payload[0:2])
        if login_result != 1:
            raise PermissionError(f"Login failed (result={login_result})")


def unlock_once(host: str, port: int, user: str, password: str,
                 channel: int = 1, action: int = 1, lockdelay: int = 1,
                 timeout: float = 8.0, video_wait_timeout: float = 5.0,
                 linger_seconds: float = 2.0, lock_pwd: str = None,
                 verbose: bool = False) -> bool:
    """Performs EXACTLY ONE unlock transaction: connect, log in, briefly wait for an
    active video channel (I-frame), send lock request, evaluate the response, close
    the connection cleanly.
    `password` = device login password (for login/video). `lock_pwd` = the PIN sent
    when opening (default: == password, as this device requires).
    Returns True if the device reported TLV_T_LOCK_RSP with result=1.
    Raises an exception on connection/protocol errors. No retry."""
    if lock_pwd is None:
        lock_pwd = password
    seq = 1
    with socket.create_connection((host, port), timeout=timeout) as sock:
        # 1. Login
        login_pkt = build_login_packet(user, password, device_id=1, channel_mask=1, sequence=seq)
        seq += 1
        sock.sendall(login_pkt)
        tlv_type, payload = _read_one_tlv_frame(sock, timeout, expect_type=TLV_LOGIN_RSP)
        if tlv_type != TLV_LOGIN_RSP:
            raise ValueError(f"Unexpected response to login: TLV type {tlv_type} (expected {TLV_LOGIN_RSP})")
        (login_result,) = struct.unpack("<h", payload[0:2])
        if verbose:
            print(f"Login response: result={login_result}", file=sys.stderr)
        if login_result != 1:
            raise PermissionError(f"Login failed (result={login_result}) -- check password")

        # 1b. Briefly wait until the video channel is demonstrably active (I-frame seen).
        _wait_for_video_active(sock, video_wait_timeout, verbose=verbose)

        # 2. Lock request (lockPwd = the entered PIN)
        lock_pkt = build_lock_packet(lock_pwd, channel=channel, action=action,
                                      lockdelay=lockdelay, sequence=seq)
        seq += 1
        sock.sendall(lock_pkt)
        tlv_type, payload = _read_one_tlv_frame(sock, timeout, expect_type=TLV_LOCK_RSP)
        if tlv_type != TLV_LOCK_RSP:
            raise ValueError(f"Unexpected response to lock request: TLV type {tlv_type} (expected {TLV_LOCK_RSP})")
        (lock_result,) = struct.unpack("<h", payload[0:2])
        if verbose:
            print(f"Lock response: result={lock_result}", file=sys.stderr)

        # 3. Clean channel teardown (like the app in closeImpl()): keep the session
        #    open briefly (keep reading frames), then send the teardown so the
        #    device/doorbell state is reset and the NEXT attempt works again (not
        #    just the first one). Errors here do not change the lock result -- the
        #    actual command is already acknowledged.
        try:
            linger_deadline = time.monotonic() + linger_seconds
            while time.monotonic() < linger_deadline:
                remaining = linger_deadline - time.monotonic()
                sock.settimeout(max(0.1, min(remaining, 0.5)))
                try:
                    if not sock.recv(65536):
                        break
                except socket.timeout:
                    continue
            teardown_pkt = build_talk_stop_packet(seq)
            seq += 1
            sock.sendall(teardown_pkt)
            if verbose:
                print("Teardown (talk stop) sent, closing channel cleanly.", file=sys.stderr)
            try:
                sock.shutdown(socket.SHUT_WR)
                sock.settimeout(1.0)
                while sock.recv(65536):
                    pass
            except OSError:
                pass
        except OSError as e:
            if verbose:
                print(f"Note: teardown not completed ({e}).", file=sys.stderr)

        return lock_result == 1


def main():
    parser = argparse.ArgumentParser(
        description="One-time, manual door opening via the GooLink TLV protocol. "
                    "NO automations, NO retry -- one call = one transaction.")
    parser.add_argument("--host", required=True, help="IP of the camera/indoor station, e.g. 192.168.1.10")
    parser.add_argument("--port", type=int, default=18600, help="TCP port (18600)")
    parser.add_argument("--user", required=True, help="WEBUI login username")
    parser.add_argument("--password", required=True,
                         help="WEBUI login password (== lockPwd). Please pass it via an "
                              "environment variable or HA secrets.yaml, do not leave it in "
                              "the shell history.")
    parser.add_argument("--channel", type=int, default=1)
    parser.add_argument("--action", type=int, default=1,
                         help="1 = as in the observed successful transaction. "
                              "Other values are NOT explored.")
    parser.add_argument("--lockdelay", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--video-wait-timeout", type=float, default=5.0,
                         help="Max wait after login for an I-frame before the lock is "
                              "sent anyway (the firmware seems to require an active "
                              "video channel).")
    parser.add_argument("--linger-seconds", type=float, default=2.0,
                         help="How long the session is kept open after the lock before "
                              "teardown+close happens (clean channel teardown, so that "
                              "subsequent triggers also work).")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    try:
        ok = unlock_once(args.host, args.port, args.user, args.password,
                          channel=args.channel, action=args.action,
                          lockdelay=args.lockdelay, timeout=args.timeout,
                          video_wait_timeout=args.video_wait_timeout,
                          linger_seconds=args.linger_seconds,
                          verbose=args.verbose)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if ok:
        print("Device reported TLV_T_LOCK_RSP result=1 (protocol success).")
        sys.exit(0)
    else:
        print("Device did not report success (result != 1).", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
