# 4-Wire Door – Home Assistant integration (GBF MR263C4 / ControlCam)

Local Home Assistant integration for the GBF MR263C4 door station ("ControlCam"):
add the device through the HA UI, open the door via an **unlock button with a PIN
prompt**, and embed the **RTSP live stream** directly.

Pure LAN path (TCP:18600), no cloud. The existing operation via the app and the
indoor-station button remains untouched.

## What the integration offers

- **Config flow (UI):** add the device with **IP address, username, password**
  (optionally name/port). The credentials are checked with a login probe when the
  device is added (login only, **no** door opening).
- **Lock entity with PIN:** when opening, HA asks for the **unlock PIN**. The door
  is opened only if it is correct. The PIN is checked locally (lockout-safe, like
  the original app) and sent to the device as `lockPwd`, which validates it
  additionally. The door status is deliberately **not** faked – the entity stays
  "locked" (there is no real status channel); opening is a momentary action.
- **Camera entity:** embeds the RTSP live stream
  (`rtsp://<host>/tcp/av1_0`, adjustable via options).

## How door opening works

A trigger opens its own, short-lived connection and does:
1. **Login** (TLV 40+41, `streamMode=SUB`/`dataType=MIXED` – exactly the app path).
2. **Wait for an active video channel** (several real I-frames + a short settle
   time) – the firmware triggers the door opener only when video is really running
   (doorbell logic).
3. **Send lock** (TLV 425, `action=1`, `lockPwd` = the entered PIN), check the reply.
4. **Clean teardown** (app packet `TalkRequest action=2`) + orderly close – so that
   subsequent triggers also work reliably.

## Installation

### Option A: HACS (as a custom repository)
1. HACS → Integrations → ⋮ → "Custom repository" → URL of this repo,
   category "Integration".
2. Install "4-Wire Door", **restart Home Assistant**.

### Option B: manual
1. Copy the folder `custom_components/fourwire_door/` into the HA config directory:
   `<config>/custom_components/fourwire_door/…`
2. Restart Home Assistant.

### Then: add the device
Settings → Devices & Services → **Add integration** → "4-Wire Door" →
enter IP address, username, password.

The entities appear under the new device:
- `lock.<name>` – open the door (with PIN prompt),
- `camera.<name>_live` – RTSP live stream.

## Options (Settings → Device → Configure)

| Option | Default | Purpose |
|---|---|---|
| Ask for PIN when opening | on | When "off", the button opens without a PIN (uses the password). |
| RTSP path | `/tcp/av1_0` | Stream path, if different. |
| Max wait for video | 6 s | Wait for real I-frames before the lock. |
| Linger before teardown | 2 s | Keep the session open before teardown. |
| Channel / action / open duration | 1 / 1 / 1 | Change only if needed (`action` = 1 = open, verified). |

## Network (Docker)

The HA container must be able to reach the door station (`<host>:18600` and RTSP
`:554`). A fixed IP is used – no broadcast/multicast discovery needed. With
`network_mode: host` this usually works without issues; in bridge mode the routing
into the camera subnet must be in place.

## Security / notes

- The device password here equals the door PIN (the protocol does not encrypt it).
  HA stores the config data in its internal database – secure access to the HA
  instance accordingly.
- **No automation:** the integration deliberately does not create any automatic
  unlocking. Opening is a deliberate user action (button + PIN).
- Leave `action` at `1` (= open, verified). Other values are unexplored.

## Planned features

Ideas on the roadmap (not yet implemented, contributions welcome):

- **Doorbell event detection** – expose an event/trigger in HA when someone rings,
  so automations can react (notifications, lights, etc.).
- **Mute the doorbell** – option to silence the chime.
- **Video motion detection + recording** – detect motion in the video stream and
  store the recorded clip.

## Alternative without a custom integration

Under `shell_command_alternative/` lies the earlier, simpler solution via
`shell_command` + script (no UI config flow, no camera). For most users the
integration above is the better choice.

## Support

If you find this integration useful and would like me to keep maintaining the
repo, I'd be happy about a donation – it goes toward the AI that helps develop and
maintain this project:

<a href="https://www.buymeacoffee.com/videejay" target="_blank">☕ Buy me a coffee</a>
