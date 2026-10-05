#!/usr/bin/env python3
"""
GBF MR263C4 / ControlCam -- manuelle Einzelaktion "Tuer oeffnen".

WICHTIG -- bitte vor Nutzung lesen:
  * Jeder Aufruf dieses Skripts ist EINE Netzwerktransaktion (ein TLV_T_LOCK_REQ).
    Es gibt KEINE Wiederholungslogik und KEIN automatisches Polling. Nicht in
    eine automation: einbinden -- nur manuell ueber script:/shell_command:
    oder einen Dashboard-Button, der von einer Person ausgeloest wird.
  * Ein "Erfolg" bedeutet nur: das Gerät hat mit TLV_T_LOCK_RSP result=1
    geantwortet (Protokoll-Quittierung). Das ist KEIN unabhängiger Nachweis,
    dass die Tür tatsaechlich offen ist -- es gibt keinen separaten Tuerstatus-
    Kanal. Nicht als Türstatus in Home Assistant anzeigen.
  * Passwort/Secrets werden nie geloggt oder auf stdout ausgegeben.

Protokoll-Kurzreferenz (siehe Bericht fuer Details und Quellenverweise):
  OwspPacketHeader (8 Byte): packet_length (4B, BIG-ENDIAN) + packet_seq (4B, LITTLE-ENDIAN)
  TLV_HEADER       (4 Byte): tlv_type (2B LE) + tlv_len (2B LE)
  Login-Request  (TLV 40 Version + TLV 41 Login, TLV_V_LoginRequestEx, 68 Byte)
  Login-Response (TLV 42, 4 Byte: result (2B LE) + reserve (2B LE))
  Lock-Request   (TLV 425, _TLV_V_Lock_Req, 42 Byte:
                  deviceId(4B LE) + lockPwd(32B, nullterm. ASCII) +
                  lockdelay(2B LE) + channel(1B) + action(1B) + reserve(2B))
  Lock-Response  (TLV 426, 4 Byte: result (2B LE) + reserve (2B LE))
"""

import argparse
import socket
import struct
import sys
import time

TLV_VERSION = 40
TLV_LOGIN_REQ = 41
TLV_LOGIN_RSP = 42
TLV_TALK_REQ = 331   # von der App in closeImpl() als Teardown mit action=2 gesendet
TLV_LOCK_REQ = 425
TLV_LOCK_RSP = 426

OWSP_HEADER_LEN = 8
TLV_HEADER_LEN = 4


def _tlv_header(tlv_type: int, tlv_len: int) -> bytes:
    # tlv_type, tlv_len: beide 2 Byte LITTLE-ENDIAN (siehe MyUtil.ChangeByteOrder-Analyse)
    return struct.pack("<HH", tlv_type, tlv_len)


def _owsp_header(packet_length: int, packet_seq: int) -> bytes:
    # packet_length: 4 Byte BIG-ENDIAN; packet_seq: 4 Byte LITTLE-ENDIAN
    return struct.pack(">I", packet_length) + struct.pack("<I", packet_seq)


def _pad(s: str, length: int) -> bytes:
    b = s.encode("ascii", errors="strict")
    if len(b) >= length:
        raise ValueError(f"Wert zu lang fuer Feldgroesse {length}: Laenge {len(b)}")
    return b + b"\x00" * (length - len(b))


#   OWSP_StreamType (com/goolink/comm/OWSP_StreamType.java): MAIN=0, SUB=1, VOD=2, MODE_SETTING=3
#   OWSP_StreamDataType (com/goolink/comm/OWSP_StreamDataType.java): VIDEO=0, AUDIO=1, MIXED=2
# MainActivity2.onSelectCamera() -- der reguläre "Kamera antippen/ansehen"-Pfad, der in
# der echten App zum erfolgreichen Türöffnen führt -- ruft
# requestSource(..., OWSP_STREAM_SUB, OWSP_MIXED_DATA, ...) auf. Ein Login mit
# streamMode=MAIN(0)/dataType=VIDEO(0) lieferte zwar TLV-100/101-Pakete, aber die
# Tür öffnete sich NICHT und der parallele RTSP-Stream blieb blau -- daher jetzt SUB/MIXED
# als Default, um den echten App-Pfad nachzubilden.
STREAM_MODE_SUB = 1
DATA_TYPE_MIXED = 2


def build_login_packet(user: str, password: str, device_id: int, channel_mask: int, sequence: int,
                        stream_mode: int = STREAM_MODE_SUB, data_type: int = DATA_TYPE_MIXED) -> bytes:
    # TLV 40: Version (4 Byte: versionMajor, versionMinor, je 2 Byte LE)
    version_payload = struct.pack("<HH", 5, 0)
    version_block = _tlv_header(TLV_VERSION, len(version_payload)) + version_payload

    # TLV 41: Login (68 Byte, siehe TLV_V_LoginRequestEx.java)
    login_payload = b"".join([
        bytes([0]),                 # encryptType
        _pad(user, 32),             # userName
        _pad(password, 16),         # password
        struct.pack("<i", device_id),   # deviceId, LE
        struct.pack("<i", 2),           # flag = 2 (fest, wie in der App)
        b"\x00\x00\x00",                # reserve3
        struct.pack("<I", channel_mask)[:4],  # channelMask (untere 4 Byte, LE)
        bytes([stream_mode]),       # streamMode -- jetzt SUB(1) statt MAIN(0), s.o.
        bytes([data_type]),         # dataType -- jetzt MIXED(2) statt VIDEO(0), s.o.
        bytes([0, 0]),               # reserve, reserve2
    ])
    assert len(login_payload) == 68, f"Login-Payload-Laenge falsch: {len(login_payload)}"
    login_block = _tlv_header(TLV_LOGIN_REQ, len(login_payload)) + login_payload

    content = version_block + login_block
    packet_length = len(content) + 4  # siehe Parser-Logik: total = content_len + 4
    return _owsp_header(packet_length, sequence) + content


def build_lock_packet(password: str, channel: int, action: int, lockdelay: int, sequence: int) -> bytes:
    lock_payload = b"".join([
        struct.pack("<i", 0),        # deviceId = 0 (wie in der App hartkodiert)
        _pad(password, 32),          # lockPwd = Geräte-/Login-Passwort
        struct.pack("<H", lockdelay),# lockdelay, LE
        bytes([channel]),            # channel
        bytes([action]),             # action (1 = aus beobachteter echter Transaktion)
        b"\x00\x00",                  # reserve
    ])
    assert len(lock_payload) == 42, f"Lock-Payload-Laenge falsch: {len(lock_payload)}"
    lock_block = _tlv_header(TLV_LOCK_REQ, len(lock_payload)) + lock_payload

    packet_length = len(lock_block) + 4
    return _owsp_header(packet_length, sequence) + lock_block


def build_talk_stop_packet(sequence: int) -> bytes:
    """Reproduziert EXAKT das Teardown-Paket, das die App in
    EyeSourceTransNet.closeImpl() vor dem Schliessen sendet:
    TalkRequestReqPack(deviceId=0, action=2). Struct TLV_V_TalkRequest (8 Byte):
    deviceId(4B LE) + action(1B) + reserve(3B). Dient dazu, den Geräte-/Doorbell-
    Zustand sauber zurückzusetzen (vermutlich SS_VI_DOORBELL_CONTROL_SET(0)), damit
    der nächste Video-Open wieder ein frischer Übergang ist -- sonst öffnet nur
    der erste Versuch die Tür."""
    talk_payload = b"".join([
        struct.pack("<i", 0),   # deviceId = 0
        bytes([2]),             # action = 2 (Stop/Teardown, wie in closeImpl())
        b"\x00\x00\x00",        # reserve[3]
    ])
    assert len(talk_payload) == 8, f"Talk-Payload-Laenge falsch: {len(talk_payload)}"
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
            raise TimeoutError(f"Zeitüberschreitung beim Lesen ({len(buf)}/{n} Byte erhalten)")
        sock.settimeout(remaining)
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Verbindung vom Gerät geschlossen")
        buf += chunk
    return buf


def _read_one_owsp_packet(sock: socket.socket, timeout: float):
    """Liest genau einen OwspPacketHeader + Inhalt und zerlegt ihn in alle
    enthaltenen TLV-Blöcke (ein Paket kann mehrere Blöcke enthalten, z.B.
    TLV 40 + TLV 42 bei der Login-Antwort)."""
    owsp_raw = _recv_exact(sock, OWSP_HEADER_LEN, timeout)
    (packet_length,) = struct.unpack(">I", owsp_raw[0:4])
    content_len = packet_length - 4
    if content_len <= 0 or content_len > 1_000_000:
        raise ValueError(f"Unplausible packet_length vom Gerät: {packet_length}")
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
        raise ValueError("Leerer TLV-Inhalt vom Gerät")
    return blocks


def _read_one_tlv_frame(sock: socket.socket, timeout: float, expect_type: int = None):
    """Liest OwspPacketHeader+Inhalt, bei Bedarf über MEHRERE aufeinanderfolgende
    Pakete hinweg, bis ein Block vom Typ expect_type gefunden wird. Das ist
    nötig, weil nach dem Login ständig Video-Frame-Pakete (TLV 99/100/101)
    dazwischenkommen koennen, bevor z.B. die Lock-Antwort (TLV 426) eintrifft --
    Ohne expect_type wird einfach der erste Block des ersten
    Pakets zurückgegeben (Alt-Verhalten). Wirft TimeoutError, wenn expect_type
    innerhalb von timeout nicht auftaucht."""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"TLV-Type {expect_type} nicht innerhalb von {timeout}s erhalten "
                f"(wahrscheinlich nur Video-Frame-Pakete dazwischen)")
        blocks = _read_one_owsp_packet(sock, remaining)
        if expect_type is None:
            return blocks[0]
        for tlv_type, payload in blocks:
            if tlv_type == expect_type:
                return tlv_type, payload
        # Kein passender Block in diesem Paket (z.B. reine Video-Frame-Pakete) --
        # naechstes Paket lesen, bis expect_type kommt oder das Zeitlimit greift.


TLV_VIDEO_IFRAME_DATA = 100


def _wait_for_video_active(sock: socket.socket, timeout: float, min_iframes: int = 3,
                            settle_seconds: float = 1.0, verbose: bool = False) -> bool:
    """Liest nach dem Login weiter vom Socket, bis MEHRERE echte I-Frames (TLV 100)
    empfangen wurden, plus eine kurze Setzzeit -- oder bis timeout ablaeuft.

    Hintergrund: Die Firmware triggert den physischen Türöffner-Ausgang beim
    Lock-Kommando offenbar nur, wenn der Video-Kanal REAL aktiv ist. Direkt nach dem
    Login beginnt das Gerät von selbst, Frames zu pushen -- aber der Kamera-Sensor
    einer Türklingel braucht eine schwankende Aufwachzeit, und die ersten
    "I-Frames" können noch blaue Platzhalter sein. Daher nicht nach dem ERSTEN
    I-Frame sofort weiter, sondern auf mehrere I-Frames (min_iframes) warten und
    danach noch settle_seconds puffern, damit der Sensor sicher real läuft.
    Gibt True zurück, wenn genug I-Frames gesehen wurden, sonst False (dann wird
    trotzdem fortgefahren, aber mit Warnung)."""
    buf = b""
    iframes = 0
    deadline = time.monotonic() + timeout
    settle_until = None
    while time.monotonic() < deadline:
        if settle_until is not None and time.monotonic() >= settle_until:
            if verbose:
                print(f"{iframes} I-Frames + Setzzeit erreicht -- sende jetzt Lock.", file=sys.stderr)
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
                            print(f"{iframes}. I-Frame -- warte noch {settle_seconds}s Setzzeit.",
                                  file=sys.stderr)
                off += 4 + tlv_len
                if tlv_len == 0:
                    break
            buf = buf[total:]
    if verbose:
        print(f"Nur {iframes} I-Frame(s) innerhalb des Timeouts -- fahre trotzdem fort.",
              file=sys.stderr)
    return iframes > 0


def probe_login(host: str, port: int, user: str, password: str,
                timeout: float = 6.0) -> None:
    """Prüft NUR Verbindung + Login (KEIN Lock, KEINE Türöffnung). Für den
    HA-Config-Flow, um Zugangsdaten/Erreichbarkeit zu validieren.
    Wirft bei Verbindungsfehler (OSError), bei Protokollfehler (ValueError) oder
    bei falschem Login (PermissionError)."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        login_pkt = build_login_packet(user, password, device_id=1, channel_mask=1, sequence=1)
        sock.sendall(login_pkt)
        tlv_type, payload = _read_one_tlv_frame(sock, timeout, expect_type=TLV_LOGIN_RSP)
        if tlv_type != TLV_LOGIN_RSP or len(payload) < 2:
            raise ValueError(f"Unerwartete Login-Antwort (TLV-Type {tlv_type})")
        (login_result,) = struct.unpack("<h", payload[0:2])
        if login_result != 1:
            raise PermissionError(f"Login fehlgeschlagen (result={login_result})")


def unlock_once(host: str, port: int, user: str, password: str,
                 channel: int = 1, action: int = 1, lockdelay: int = 1,
                 timeout: float = 8.0, video_wait_timeout: float = 5.0,
                 linger_seconds: float = 2.0, lock_pwd: str = None,
                 verbose: bool = False) -> bool:
    """Führt GENAU EINE Entriegelungs-Transaktion aus: verbinden, einloggen,
    kurz auf aktiven Video-Kanal warten (I-Frame), Lock-Request senden,
    Antwort auswerten, Verbindung sauber schliessen.
    `password` = Geräte-Login-Passwort (für Login/Video). `lock_pwd` = die beim
    Öffnen gesendete PIN (Default: == password, wie es dieses Geraet verlangt).
    Gibt True zurück, wenn das Gerät TLV_T_LOCK_RSP mit result=1 gemeldet hat.
    Wirft eine Exception bei Verbindungs-/Protokollfehlern. Keine Wiederholung."""
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
            raise ValueError(f"Unerwartete Antwort auf Login: TLV-Type {tlv_type} (erwartet {TLV_LOGIN_RSP})")
        (login_result,) = struct.unpack("<h", payload[0:2])
        if verbose:
            print(f"Login-Antwort: result={login_result}", file=sys.stderr)
        if login_result != 1:
            raise PermissionError(f"Login fehlgeschlagen (result={login_result}) -- Passwort prüfen")

        # 1b. Kurz warten, bis der Video-Kanal nachweislich aktiv ist (I-Frame gesehen).
        _wait_for_video_active(sock, video_wait_timeout, verbose=verbose)

        # 2. Lock-Request (lockPwd = die eingegebene PIN)
        lock_pkt = build_lock_packet(lock_pwd, channel=channel, action=action,
                                      lockdelay=lockdelay, sequence=seq)
        seq += 1
        sock.sendall(lock_pkt)
        tlv_type, payload = _read_one_tlv_frame(sock, timeout, expect_type=TLV_LOCK_RSP)
        if tlv_type != TLV_LOCK_RSP:
            raise ValueError(f"Unerwartete Antwort auf Lock-Request: TLV-Type {tlv_type} (erwartet {TLV_LOCK_RSP})")
        (lock_result,) = struct.unpack("<h", payload[0:2])
        if verbose:
            print(f"Lock-Antwort: result={lock_result}", file=sys.stderr)

        # 3. Sauberer Kanal-Abbau (wie die App in closeImpl()): Sitzung kurz offen
        #    halten (Frames weiterlesen), dann Teardown senden, damit der Geräte-/
        #    Doorbell-Zustand zurückgesetzt wird und der NÄCHSTE Versuch wieder
        #    funktioniert (nicht nur der erste). Fehler hier ändern das Lock-Ergebnis
        #    nicht -- der eigentliche Befehl ist bereits quittiert.
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
                print("Teardown (Talk-Stop) gesendet, schliesse Kanal sauber.", file=sys.stderr)
            try:
                sock.shutdown(socket.SHUT_WR)
                sock.settimeout(1.0)
                while sock.recv(65536):
                    pass
            except OSError:
                pass
        except OSError as e:
            if verbose:
                print(f"Hinweis: Teardown nicht vollständig ({e}).", file=sys.stderr)

        return lock_result == 1


def main():
    parser = argparse.ArgumentParser(
        description="Einmalige, manuelle Türöffnung über das GooLink-TLV-Protokoll. "
                    "KEINE Automationen, KEINE Wiederholung -- ein Aufruf = eine Transaktion.")
    parser.add_argument("--host", required=True, help="IP der Kamera/Innenstation, z.B. 192.168.1.10")
    parser.add_argument("--port", type=int, default=18600, help="TCP-Port (18600)")
    parser.add_argument("--user", required=True, help="WEBUI-Login-Benutzername")
    parser.add_argument("--password", required=True,
                         help="WEBUI-Login-Passwort (== lockPwd). Bitte über Umgebungsvariable "
                              "oder HA secrets.yaml übergeben, nicht in der Shell-History belassen.")
    parser.add_argument("--channel", type=int, default=1)
    parser.add_argument("--action", type=int, default=1,
                         help="1 = wie in der beobachteten erfolgreichen Transaktion. "
                              "Andere Werte sind NICHT erforscht.")
    parser.add_argument("--lockdelay", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--video-wait-timeout", type=float, default=5.0,
                         help="Max. Wartezeit nach Login auf ein I-Frame, bevor Lock "
                              "trotzdem gesendet wird (Firmware scheint einen aktiven "
                              "Video-Kanal vorauszusetzen).")
    parser.add_argument("--linger-seconds", type=float, default=2.0,
                         help="Wie lange nach dem Lock die Sitzung offen gehalten wird, "
                              "bevor Teardown+Close erfolgt (sauberer Kanal-Abbau, damit "
                              "auch Folgeauslösungen funktionieren).")
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
        print(f"FEHLER: {e}", file=sys.stderr)
        sys.exit(1)

    if ok:
        print("Geraet hat TLV_T_LOCK_RSP result=1 gemeldet (Protokoll-Erfolg).")
        sys.exit(0)
    else:
        print("Geraet hat keinen Erfolg gemeldet (result != 1).", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
