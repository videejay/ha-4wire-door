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

# hass.data key for the manual video sessions (per config entry)
VIDEO_SESSIONS = "video_sessions"
# Safety cap: a manually started video session ends by itself after this time.
VIDEO_SESSION_MAX_SECONDS = 300.0

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

# --- Doorbell via GB28181 (local SIP push from the device) ---
CONF_GB_ENABLED = "gb28181_enabled"
CONF_GB_PORT = "gb28181_port"
DEFAULT_GB_ENABLED = True
DEFAULT_GB_PORT = 5060
# hass.data key for the receiver state (per config entry)
GB_STATES = "gb28181_states"
# "Doorbell channel" goes off when nothing arrived for this long
# (device heartbeat default 60 s -> 3 missed keepalives).
GB_STALE_SECONDS = 200
# Dispatcher signal for a ring (format with entry_id)
SIGNAL_RING = "fourwire_door_ring_{}"
# HA bus event fired on every ring
EVENT_RING = "fourwire_door_doorbell"
# A video start by THIS integration (video button / door opening) also raises the
# motion alarm. Alarms during an own session or shortly after it are not
# reported as a ring.
OWN_ACTIVITY_SUPPRESS_SECONDS = 15.0
OWN_ACTIVITY = "own_activity"
