# DarkSec Chat for WiFi Pineapple Pager

This payload sends and receives messages from `https://darksec.uk/chat` using
the site's JSON API and Hak5's native Pager interface.

## Why the native interface

The active payload does not stop `pineapplepager` or take over the LCD through
`pagerctl`. Button input uses `WAIT_FOR_INPUT`, output uses `LOG`, and pressing
A invokes the built-in `TEXT_PICKER` directly. This is the same supported flow
used by Hak5's picker examples and avoids competing with the service that owns
the Pager buttons and keyboard.

Network polling runs in a separate process. Slow DNS, TLS, or API responses do
not block button handling.

## Features

- A/green opens the native system keyboard.
- B/red or Power exits.
- New messages appear through the native Pager log interface.
- Incoming messages poll incrementally with `GET /api/chat?after=<id>`.
- Outgoing messages use `POST /api/chat` with JSON.
- The initial sync shows only the latest eight messages.
- Poll state and diagnostic logs persist under `/root/loot/darksec-chat/`.
- No `requests`, `pagerctl.py`, or `libpagerctl.so` dependency.

## Files

```text
payload.sh          Native Pager UI and responsive input loop
darksec_native.py   Dependency-free DarkSec API helper
config.sh           API URL and username
darksec_chat.py     Legacy custom-LCD/mesh implementation; not launched
pagerctl.py         Legacy custom-LCD wrapper; not required
```

## Requirements

- WiFi Pineapple Pager with Internet access
- Python 3
- Working device date/time for HTTPS certificate validation

## Installation

Copy at least these three files into one Pager payload directory:

```text
/root/payloads/user/general/darksec-pineapple-chat/
  payload.sh
  darksec_native.py
  config.sh
```

Hak5 supplies the actual installed directory as `_PAYLOAD_HOME`; the launcher
uses it automatically.

## Configuration

Edit `config.sh`:

```sh
export WEB_API_URL=""
export USERNAME="PagerUser"
```

An empty URL selects `https://darksec.uk/api/chat`.

## API contract

```text
GET /api/chat
GET /api/chat?after=<last_message_id>
POST /api/chat
Content-Type: application/json
```

POST body:

```json
{"username":"PagerUser","message":"hello from the Pager"}
```

Messages returned by GET use `id`, `username`, `message`, and `created_at`.

## Diagnostics

The persistent runtime log is:

```text
/root/loot/darksec-chat/darksec_chat.log
```

To test the endpoint independently over SSH:

```sh
python3 /root/payloads/user/general/darksec-pineapple-chat/darksec_native.py \
  poll https://darksec.uk/api/chat /tmp/darksec-test-state.json
```
