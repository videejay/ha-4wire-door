#!/usr/bin/env python3
"""
Home Assistant entry point for the manual door opening (GBF MR263C4 / ControlCam).

Called by HA via shell_command and performs EXACTLY ONE door-opening transaction
(login -> wait for active video channel -> lock -> clean teardown). No loop, no
retry, no automation.

Credentials come from a SEPARATE file (JSON), NOT from the command line (so that
they are not visible in the process list). Path via the environment variable
DOOR_CONFIG or default: door_secrets.json next to this script.

Uses only the Python standard library (json/socket/struct) -- no extra packages
needed in the HA container. The actual protocol lives in door_protocol.py (must be
in the same directory).

Return: exit 0 = device reported TLV_T_LOCK_RSP result=1 (protocol success). This is
NOT independent proof that the door is physically open (there is no door-status
channel) -- never surface it in HA as a door-status/lock entity with state.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from door_protocol import unlock_once


def load_config():
    cfg_path = os.environ.get("DOOR_CONFIG") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "door_secrets.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: configuration file not found: {cfg_path}", file=sys.stderr)
        sys.exit(3)
    except (ValueError, OSError) as e:
        print(f"ERROR reading the configuration: {e}", file=sys.stderr)
        sys.exit(3)
    for key in ("host", "user", "password"):
        if not cfg.get(key):
            print(f"ERROR: required field '{key}' missing in the configuration.", file=sys.stderr)
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
        # The password does not appear in our exceptions.
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if ok:
        print("OK: device reported protocol success (result=1).")
        sys.exit(0)
    print("FAILURE: device did not report success (result != 1).", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
