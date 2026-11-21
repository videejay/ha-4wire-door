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
- `camera.<name>_live` – RTSP live stream,
- `button.<name>_video_signal_on` / `button.<name>_video_signal_off` – manually
  switch the video signal on/off (see below).

## Video signal on / off

Without an active client session the camera sensor of the door station only
delivers a **blue picture** on RTSP. "Video signal on" logs in exactly like the app
(`streamMode=SUB`, `dataType=MIXED`) and keeps that session open; "Video signal
off" ends it with the app's teardown packet.

- Neither button sends a lock request – **they never open the door**.
- No retry/reconnect: if the device drops the connection, the session is simply over.
- Safety cap: a started session ends by itself after 300 s.
- Opening the door runs its own short session and ends it with the teardown packet,
  which also switches the video signal off. Press "on" again afterwards if needed.
- Whether the video signal stays stable in parallel to the app is not verified.

## Doorbell event (local, via GB28181)

The door station has a built-in GB28181 (SIP) client. Pointed at Home Assistant,
it pushes an alarm when someone rings, with no cloud involved. The integration runs a small
receiver for it (UDP 5060 by default) and provides:

- `event.<name>_doorbell`: event type `ring` on every ring. Use it in automations
  ("Entity → Event → Doorbell").
- HA bus event `fourwire_door_doorbell` (data: `entry_id`, `alarm_method`,
  `alarm_time`, …).
- `binary_sensor.<name>_doorbell_channel` (diagnostic): "connected" while the device is
  registered and its keepalives (every 60 s) arrive. If it goes off, rings are
  **not** delivered.

### One-time setup on the device
Open `http://<device-ip>/gb28181.asp` (the page is hidden in the device menu) and set:

| Field | Value |
|---|---|
| Server ID | `34020000002000000001` |
| Server address | IP of the HA host/container |
| Server port | `5060` (= option "Doorbell receiver UDP port") |
| Device ID | `34020000001320000001` |
| Device port | `5060` |
| Media channel ID / Alarming channel ID | `34020000001310000001` / `34020000001340000001` |
| Registration valid time / Heartbeating time | `3600` / `60` |

Then click **Save**. Within about a minute the device registers and the channel sensor
turns on.

### How it works / limitations
- When someone rings, the indoor station switches the camera on. The firmware raises a ~6 s
  **motion alarm** (`AlarmMethod 5`) and sends it as SIP `MESSAGE`. The receiver only
  answers REGISTER/MESSAGE with `200 OK`. It never sends its own requests.
- The device **sets its clock** from the `Date` header of that `200 OK` (HA time zone).
- Video started by this integration (video button, door opening) raises the same
  alarm. It is suppressed for 15 s. **Video opened in the ControlCam app cannot be told
  apart from a ring.** Real motion in front of the camera while the video is on can
  also trigger it.
- If the receiver is unreachable for a longer time (seen: PC standby ~2.5 h), the device
  did not register again on its own, and the "Register" button on its page did not
  help either. **Saving the GB28181 page again (unchanged values)** brought it back. A short HA
  restart is not yet verified. Watch the channel sensor.
- The HA container needs its own LAN IP or `network_mode: host` so that UDP 5060 is
  reachable from the device.

## Options (Settings → Device → Configure)

| Option | Default | Purpose |
|---|---|---|
| Ask for PIN when opening | on | When "off", the button opens without a PIN (uses the password). |
| RTSP path | `/tcp/av1_0` | Stream path, if different. |
| Max wait for video | 6 s | Wait for real I-frames before the lock. |
| Linger before teardown | 2 s | Keep the session open before teardown. |
| Channel / action / open duration | 1 / 1 / 1 | Change only if needed (`action` = 1 = open, verified). |
| Doorbell receiver (GB28181) active | on | Run the local SIP receiver for the doorbell event. |
| Doorbell receiver UDP port | 5060 | Must match "Server port" on the device page. |

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
