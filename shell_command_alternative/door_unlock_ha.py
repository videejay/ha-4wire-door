#!/usr/bin/env python3
"""
Home-Assistant-Einstiegspunkt für die manuelle Türööffnung (GBF MR263C4 / ControlCam).

Wird von HA ueber shell_command aufgerufen und fuehrt GENAU EINE Türööffnungs-
Transaktion aus (Login -> auf aktiven Video-Kanal warten -> Lock -> sauberer
Teardown). Kein Loop, kein Retry, keine Automatik.

Zugangsdaten kommen aus einer SEPARATEN Datei (JSON), NICHT von der Kommandozeile
(damit sie nicht in der Prozessliste sichtbar sind). Pfad per Umgebungsvariable
DOOR_CONFIG oder Standard: door_secrets.json neben diesem Skript.

Nutzt nur die Python-Standardbibliothek (json/socket/struct) -- keine Zusatzpakete
im HA-Container noetig. Das eigentliche Protokoll liegt in
door_protocol.py (muss im selben Verzeichnis liegen).

Rückgabe: Exit 0 = Gerät hat TLV_T_LOCK_RSP result=1 gemeldet (Protokoll-Erfolg).
Das ist KEIN unabhängiger Nachweis, dass die Tür physisch offen ist (es gibt keinen
Türstatus-Kanal) -- in HA niemals als Türstatus/Schloss-Entität mit Zustand führen.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ha_door_unlock_single_action import unlock_once


def load_config():
    cfg_path = os.environ.get("DOOR_CONFIG") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "door_secrets.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        print(f"FEHLER: Konfigurationsdatei nicht gefunden: {cfg_path}", file=sys.stderr)
        sys.exit(3)
    except (ValueError, OSError) as e:
        print(f"FEHLER beim Lesen der Konfiguration: {e}", file=sys.stderr)
        sys.exit(3)
    for key in ("host", "user", "password"):
        if not cfg.get(key):
            print(f"FEHLER: Pflichtfeld '{key}' fehlt in der Konfiguration.", file=sys.stderr)
            sys.exit(3)
    return cfg


def main():
    cfg = load_config()
    try:
        ok = unlock_once(
            host=str(cfg["host"]),
            port=int(cfg.get("port", 18600)),
            user=str(cfg["user"]),
            password=str(cfg["password"]),
            channel=int(cfg.get("channel", 1)),
            action=int(cfg.get("action", 1)),
            lockdelay=int(cfg.get("lockdelay", 1)),
            timeout=float(cfg.get("timeout", 8.0)),
            video_wait_timeout=float(cfg.get("video_wait_timeout", 6.0)),
            linger_seconds=float(cfg.get("linger_seconds", 2.0)),
            verbose=bool(cfg.get("verbose", False)),
        )
    except Exception as e:
        # Passwort taucht in unseren Exceptions nicht auf.
        print(f"FEHLER: {e}", file=sys.stderr)
        sys.exit(1)

    if ok:
        print("OK: Gerät hat Protokoll-Erfolg gemeldet (result=1).")
        sys.exit(0)
    print("FEHLSCHLAG: Gerät hat keinen Erfolg gemeldet (result != 1).", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
