"""Konstanten fuer die 4-Wire-Door-Integration (GBF MR263C4 / ControlCam)."""

DOMAIN = "fourwire_door"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_NAME = "name"

# Optionale Feineinstellungen (Options-Flow)
CONF_CHANNEL = "channel"
CONF_ACTION = "action"
CONF_LOCKDELAY = "lockdelay"
CONF_VIDEO_WAIT_TIMEOUT = "video_wait_timeout"
CONF_LINGER_SECONDS = "linger_seconds"
CONF_RTSP_PATH = "rtsp_path"
CONF_REQUIRE_PIN = "require_pin"

DEFAULT_PORT = 18600
DEFAULT_NAME = "Haustür"
DEFAULT_CHANNEL = 1
DEFAULT_ACTION = 1  # 1 = öffnen (verifiziert); andere Werte unerforscht
DEFAULT_LOCKDELAY = 1
DEFAULT_VIDEO_WAIT_TIMEOUT = 6.0
DEFAULT_LINGER_SECONDS = 2.0
# funktionierender RTSP-Pfad fuer dieses Gerät:
DEFAULT_RTSP_PATH = "/tcp/av1_0"
# PIN-Format fuer die Lock-Entität (UI-Abfrage): mind. 1 Zeichen, Ziffern/Buchstaben.
PIN_CODE_FORMAT = r"^.{1,32}$"

MANUFACTURER = "GBF"
MODEL = "MR263C4 (ControlCam)"
