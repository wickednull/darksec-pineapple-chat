<img width="1408" height="768" alt="image" src="https://github.com/user-attachments/assets/d9cd930a-42f2-4204-a9ec-9711dc3a1d80" />


# DARKSEC // PAGER CHAT

> Field communications for the Hak5 WiFi Pineapple Pager.

DarkSec-Chat turns the Pager into a compact, themed communications console. It
bridges directly into the live chat also,
discovers nearby DarkSec Pagers over the local network, and keeps the interface
fast enough for actual handheld use.

```text
┌──────────────────────────────────────────────────────────────┐
│  DARKSEC CHAT                                                │
│  HTTPS WEB BRIDGE  //  LOCAL PEER COMMS  //  PAGERCTL UI    │
└──────────────────────────────────────────────────────────────┘
```

## Mission profile

- Send and receive messages through the DarkSec website chat.
- Discover other DarkSec Pagers on the same local network.
- Exchange direct peer messages over persistent TCP connections.
- Operate through a custom `pagerctl` LCD interface.
- Retain message history, identity, theme, and diagnostic logs on-device.
- Stay usable when the website is unreachable by preserving local peer comms.

This is a communications payload with encrypted local mesh support. Website traffic
uses HTTPS. Local mesh traffic requires a shared key and uses versioned
ChaCha20 encryption with HMAC-SHA256 authentication; mesh is disabled otherwise.
The public website bridge still lacks end-to-end encryption and authenticated
user identities, so do not use that bridge for sensitive traffic.

## Capabilities

### DarkSec web bridge

The Pager speaks to the same JSON API used by the DarkSec web client:

```http
GET  https://darksec.uk/api/chat
GET  https://darksec.uk/api/chat?after=<last_message_id>
POST https://darksec.uk/api/chat
Content-Type: application/json
```

Outgoing message:

```json
{"username":"PagerUser","message":"hello from the field"}
```

The initial sync loads only the newest messages so a large server backlog does
not stall the display. After that, the Pager asks only for messages newer than
the last ID it received. Website polling runs once per second, and sends run in
a background thread so network delays do not freeze the controls.

The current website API does not provide user authentication. A username is a
display label, not verified identity.

### Local peer discovery

Every running Pager advertises a small presence record by UDP broadcast:

```text
Discovery: UDP/9999 broadcast
Chat:      TCP/9998 peer connection
```

Presence record:

```json
{"type":"presence","username":"PagerUser","ip":"192.168.1.25"}
```

When another DarkSec Pager hears the broadcast, it opens a direct TCP
connection and sends a username handshake. Chat messages then travel over that
connection:

```json
{"type":"chat","text":"local message"}
```

Discovery normally remains inside the local subnet. Client isolation, VLANs,
or firewall rules may block UDP `9999` or TCP `9998`.

### Operator interface

- Chronological transcript with the newest messages at the bottom.
- Automatic follow mode while viewing the newest messages.
- Revision-based web-message follow mode remains pinned to the true newest
  message even when the saved transcript has reached its 500-message limit.
- Stable scroll position while reviewing older traffic.
- Large in-app keyboard with lowercase, `SHIFT`, numbers, punctuation,
  `SPACE`, `BSP`, and `SEND`.
- Event-queue button handling with state-polling fallback.
- Event-driven screen rendering instead of continuous full-frame redraws.
- Web and mesh status indicators.
- Adjustable display brightness.
- Persistent launcher, transport, and crash diagnostics.

## Controls

### Chat

| Control | Action |
| --- | --- |
| `A / GREEN` | Open message keyboard |
| `UP` | Scroll toward older messages |
| `DOWN` | Scroll toward newer messages |
| `B / RED` | Open pause menu |
| `POWER` | Exit DarkSec-Chat |

### Keyboard

| Control | Action |
| --- | --- |
| D-pad | Navigate keys |
| `A / GREEN` | Select key |
| `B / RED` | Backspace |
| `SHIFT` | Toggle uppercase |
| `SHIFT^` | Uppercase is active |
| `SEND` | Submit message |

Horizontal keyboard navigation wraps at both ends of every row. For example,
moving right from `P` selects `Q`, while moving left from `Q` selects `P`.
Vertical navigation also wraps: moving up from the top character row reaches
the action row, and moving down from the action row returns to the top.

### Pause menu

| Control | Action |
| --- | --- |
| `UP / DOWN` | Select option |
| `LEFT / RIGHT` | Adjust brightness or theme |
| `A / GREEN` | Activate option |
| `B / RED` | Return to chat |

## Themes

- **DarkSec** — black, cyan, and green operations console.
- **Amber CRT** — warm amber terminal profile.
- **Matrix** — high-contrast green-on-black profile.
- **Ice** — cold blue low-light profile.

Theme selection persists at:

```text
/root/loot/darksec-chat/theme.txt
```

## Deployment

Copy the payload into a user payload directory on the Pager:

```text
/root/payloads/user/general/darksec-chat/
├── payload.sh
├── darksec_chat.py
├── config.sh
├── pagerctl.py
├── lib/
│   └── libpagerctl.so
└── fonts/                  # optional TTF fonts
```

The directory name may differ. The launcher first uses Hak5's `_PAYLOAD_HOME`
or its own real directory and retains known-location fallbacks for compatibility.
This prevents an older parallel installation from being launched accidentally.

### Requirements

- Hak5 WiFi Pineapple Pager
- Python 3
- `python3-ctypes`
- `pagerctl.py`
- `libpagerctl.so`
- Internet access for the DarkSec website bridge

The payload does not use or require the Python `requests` package. HTTP uses
Python's standard `urllib.request` module and automatically falls back to the
Pager's `curl` command.

The launcher searches the payload, standard PAGERCTL utility locations, and
system library locations. It stages `pagerctl.py` and `libpagerctl.so` together
under `/tmp/darksec-chat-lib` before starting Python.

Do not run `opkg upgrade` on the Pager. If Python packages are required, install
only the specific packages needed by the payload.

## Configuration

Edit `config.sh`:

```sh
export WEB_API_URL=""
export USERNAME="PagerUser"
export UDP_PORT=9999
export TCP_PORT=9998
export MESH_SHARED_KEY=""
```

Mesh networking is disabled until `MESH_SHARED_KEY` contains at least 32
characters. Generate a 32-byte random key and copy the same value to every trusted
Pager. Discovery, handshakes, and messages use ChaCha20 encryption with
HMAC-SHA256 authentication and reject stale or replayed packets. This protocol
requires matching current DarkSec-Chat versions and shared keys on all peers.

```sh
openssl rand -hex 32
```

An empty `WEB_API_URL` selects:

```text
https://darksec.uk/api/chat
```

An alternate endpoint must implement the same GET/POST JSON contract.

## How it works

```text
                         INTERNET
                             │
                    HTTPS GET / POST
                             │
                    darksec.uk/api/chat
                             │
            ┌────────────────┴────────────────┐
            │                                 │
       DarkSec Pager A                   Browser users
            │
            ├── UDP/9999 presence broadcast
            │
            └── TCP/9998 direct chat ───── DarkSec Pager B
```

`payload.sh` resolves dependencies, stages the PAGERCTL runtime, stops the
standard Pager UI, and launches `darksec_chat.py`. The Python application owns
the display until exit. Cleanup restores the standard Pager service.

The in-app keyboard is intentional. Current firmware rejects a native
DuckyScript `TEXT_PICKER` after the custom `pagerctl` display session has taken
over, so message composition stays inside the same responsive LCD session.

## Persistence and logs

| Path | Purpose |
| --- | --- |
| `/root/loot/darksec-chat/messages.json` | Recent transcript |
| `/root/loot/darksec-chat/username.txt` | Operator display name |
| `/root/loot/darksec-chat/theme.txt` | Selected theme |
| `/root/loot/darksec-chat/darksec_chat.log` | Launcher and runtime transitions |
| `/root/loot/darksec-chat/darksec_chat_app.log` | API, send, input, and crash diagnostics |

Useful field checks:

```sh
tail -n 50 /root/loot/darksec-chat/darksec_chat.log
tail -n 50 /root/loot/darksec-chat/darksec_chat_app.log
curl -v https://darksec.uk/api/chat
```

## Troubleshooting

### The payload returns to the menu

Inspect both logs. Confirm Python, `python3-ctypes`, `pagerctl.py`, and
`libpagerctl.so` are available. The wrapper and shared library must be staged
together because Hak5 payloads execute from `/tmp`.

### `WEB --` remains visible

Confirm the Pager has Internet access, DNS works, and its date/time is correct
for HTTPS certificate validation. Test the endpoint with `curl` from SSH.

### Local Pagers do not discover each other

Confirm both devices are on the same subnet and use matching ports. Disable
client isolation or place the Pagers on a network that permits peer traffic.

### Messages send locally but not to the website

Search `darksec_chat_app.log` for `web_post failed`. HTTP status `0` means the
request failed before receiving an HTTP response—usually DNS, TLS, routing, or
timeout failure.

## Security notes

- The DarkSec website API currently accepts an unverified username.
- Local mesh traffic is encrypted and authenticated when a shared key is
  configured.
- Mesh networking stays disabled when no sufficiently long shared key exists.
- The website API is HTTPS transport-encrypted but does not currently provide
  end-to-end message encryption or authenticated user identities.
- Use only on networks and systems you own or are authorized to operate on.

Future hardening candidates include per-device identities, key rotation, and an
optional authenticated pub/sub transport.

## Credits and attribution

- **wickednull** — DarkSec-Chat author, Pager integration, UI, web bridge, mesh
  transport, themes, keyboard, and ongoing development.
- **[sinXne0](https://github.com/sinXne0)** — project partner and developer of
  the DarkSec website at `darksec.uk`, including the website chat and API that
  power the Pager's web communications bridge.
- **brAinphreAk** — creator and copyright holder of **PAGERCTL**, the Pager
  hardware-control library and Python wrapper that make the custom LCD,
  buttons, LEDs, brightness, fonts, and responsive input possible. The bundled
  `pagerctl.py` carries the original 2025 MIT license and copyright notice.
- **Hak5** — creator of the WiFi Pineapple Pager, its payload platform,
  DuckyScript environment, and device ecosystem.
- **DarkSec** — the community and service this payload connects to.

DarkSec-Chat is an independent community project. It is not an official Hak5
product and is not presented as endorsed by Hak5 or the PAGERCTL author.

## License

PAGERCTL remains governed by its included MIT license and original
`Copyright (c) 2025 brAinphreAk` notice. Preserve that notice when
redistributing `pagerctl.py` or PAGERCTL components.

