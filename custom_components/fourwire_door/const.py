"""Constants for the 4-Wire Door integration (GBF MR263C4 / ControlCam)."""

DOMAIN = "fourwire_door"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_NAME = "name"

# Optional fine-tuning (options flow)
CONF_CHANNEL = "channel"
CONF_ACTION = "action"
CONF_LOCKDELAY = "lockdelay"
CONF_VIDEO_WAIT_TIMEOUT = "video_wait_timeout"
CONF_LINGER_SECONDS = "linger_seconds"
CONF_RTSP_PATH = "rtsp_path"
CONF_REQUIRE_PIN = "require_pin"

DEFAULT_PORT = 18600
DEFAULT_NAME = "Front Door"
DEFAULT_CHANNEL = 1
DEFAULT_ACTION = 1  # 1 = open (verified); other values unexplored
DEFAULT_LOCKDELAY = 1
DEFAULT_VIDEO_WAIT_TIMEOUT = 6.0
DEFAULT_LINGER_SECONDS = 2.0
# working RTSP path for this device:
DEFAULT_RTSP_PATH = "/tcp/av1_0"
# PIN format for the lock entity (UI prompt): at least 1 character, digits/letters.
PIN_CODE_FORMAT = r"^.{1,32}$"

MANUFACTURER = "GBF"
MODEL = "MR263C4 (ControlCam)"
