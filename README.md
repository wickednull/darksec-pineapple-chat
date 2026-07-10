# DarkSec-Chat for WiFi Pineapple Pager

DarkSec-Chat is a WiFi Pineapple Pager payload that lets the Pager join the DarkSec website chat directly from the device. It also keeps the local mesh chat mode, so multiple Pagers on the same LAN can discover each other and exchange messages.

## What Works

- Pager LCD chat UI with message history, scrolling, pause menu, and on-screen keyboard.
- Four selectable UI themes: DarkSec, Amber CRT, Matrix, and Ice.
- Direct website chat bridge for the DarkSec `/api/chat` endpoint.
- Efficient polling with `GET /api/chat?after=<last_id>` after the first sync.
- Message send with `POST /api/chat` and JSON body `{ "username": "...", "message": "..." }`.
- Mesh peer discovery over UDP and message exchange over TCP.
- Local persistence for username and recent messages under `/root/loot/darksec-chat/`.
- Optional TTF font rendering when a compatible font is available.

## Files

```text
darksec/
├── payload.sh        # Pager launcher, dependency checks, pagerctl setup
├── darksec_chat.py   # Chat UI, mesh networking, website bridge
├── config.sh         # Website URL, username, mesh ports
├── pagerctl.py       # Python wrapper for libpagerctl.so
├── lib/              # Put libpagerctl.so here
└── fonts/            # Optional .ttf fonts
```

## Install


The payload expects to run from:

```text
/root/payloads/user/general/darksec-chat
```

`payload.sh` looks for `libpagerctl.so` and `pagerctl.py` in:

- `/root/payloads/user/general/darksec-chat/lib`
- `/root/payloads/user/general/darksec-chat`
- `/mmc/root/payloads/user/utilities/PAGERCTL`

## Requirements

- WiFi Pineapple Pager.
- Python 3.
- `python3-ctypes`.
- `libpagerctl.so` and `pagerctl.py`.
- `python3-requests` for website chat support.

If Python 3 or `ctypes` is missing, the payload can offer to install them with `opkg`. If `python3-requests` is missing, mesh chat still works but website chat is disabled.

## Configure Website Chat

Edit `config.sh` before running:

```sh
export WEB_API_URL=""
export USERNAME="PagerUser"
export UDP_PORT=9999
export TCP_PORT=9998
```

By default, blank `WEB_API_URL` uses:

```text
https://darksec.uk/api/chat
```

To connect a different website, set the full endpoint:

```sh
export WEB_API_URL="https://your-site.example/api/chat"
```

The website endpoint must support this contract:

```text
GET /api/chat
GET /api/chat?after=<last_message_id>
POST /api/chat
Content-Type: application/json
```

POST body:

```json
{
  "username": "PagerUser",
  "message": "hello from the pager"
}
```

GET response:

```json
[
  {
    "id": 123,
    "username": "RemoteUser",
    "message": "hello pager",
    "created_at": "2026-07-10T08:45:00Z"
  }
]
```

The bridge also accepts a wrapped response:

```json
{
  "messages": [
    {
      "id": 123,
      "username": "RemoteUser",
      "message": "hello pager",
      "created_at": "2026-07-10T08:45:00Z"
    }
  ]
}
```

## Controls

| Button | Action |
| --- | --- |
| UP / DOWN | Scroll chat history |
| A / GREEN | Open keyboard and send a message |
| B / RED | Open pause menu |
| POWER | Exit |

Keyboard controls:

| Button | Action |
| --- | --- |
| DPAD | Move between keys |
| A / GREEN | Select highlighted key |
| B / RED | Backspace or cancel |

Pause menu controls:

| Button | Action |
| --- | --- |
| UP / DOWN | Move between menu items |
| LEFT / RIGHT | Adjust brightness or cycle themes |
| A / GREEN | Select |
| B / RED | Return to chat |

## Mesh Chat

Mesh mode uses:

- UDP port `9999` for presence broadcasts.
- TCP port `9998` for peer chat streams.

All peers must use the same ports. Mesh messages are sent to connected peers. Website messages are shown on the Pager and forwarded to mesh peers with a `[Web]` prefix.

## Persistence

| Data | Location |
| --- | --- |
| Message history | `/root/loot/darksec-chat/messages.json` |
| Username | `/root/loot/darksec-chat/username.txt` |
| Selected theme | `/root/loot/darksec-chat/theme.txt` |

The message history keeps the most recent 500 messages.

## Themes

Open the pause menu with **B / RED**, move to the **Theme** row, then use **LEFT / RIGHT** to cycle styles.

Built-in themes:

- **DarkSec**: black, cyan, and green terminal styling.
- **Amber CRT**: black and amber, high contrast for low light.
- **Matrix**: black and green, classic terminal look.
- **Ice**: dark navy, white, and blue dashboard styling.

The selected theme is saved automatically and restored on the next launch.

## Troubleshooting

### Website chat does not connect

- Install `python3-requests`.
- Confirm the Pager has internet access.
- Confirm the endpoint responds to `GET /api/chat`.
- If using your own website, confirm it supports `GET /api/chat?after=<id>`.

### Messages send but do not appear

- Check that the website returns numeric `id` values.
- Check that returned messages use `username`, `message`, and `created_at`.
- Make sure the Pager username is not identical to the remote sender you expect to see. The bridge hides echoes from the current username.

### pagerctl is missing

Copy `libpagerctl.so` and `pagerctl.py` into:

```text
/root/payloads/user/general/darksec-chat/lib/
```

### Font rendering is basic

Add a TTF font such as `DejaVuSansMono.ttf` to:

```text
/root/payloads/user/general/darksec-chat/fonts/
```

## Notes

Use this payload only on networks and services you own or are authorized to use. The website bridge is intended for your own DarkSec chat endpoint or compatible self-hosted chat endpoints.
