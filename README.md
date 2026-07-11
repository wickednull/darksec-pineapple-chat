# DarkSec-Chat for WiFi Pineapple Pager

The themed `pagerctl` application connects directly to
`https://darksec.uk/chat` through its JSON API while retaining mesh chat,
history, scrolling, brightness controls, and all four visual themes.

## Controls

- A/green: open the responsive in-app Pager keyboard and send
- Up/down: scroll messages
- B/red: pause menu
- Power: exit

## Themes

The pause menu retains DarkSec, Amber CRT, Matrix, and Ice themes. The selected
theme is stored at `/root/loot/darksec-chat/theme.txt`.

The keyboard uses large, screen-filling keys and defaults to lowercase.
Navigate with the D-pad, press A to select, use SHIFT/SHIFT^ to toggle letter
case, press B to erase, and choose SEND from the bottom action row.

## Required files

```text
payload.sh
darksec_chat.py
config.sh
pagerctl.py
lib/libpagerctl.so
```

The launcher can also use a PAGERCTL installation from the standard Pager
utility directories. Python 3 and `python3-ctypes` are required.

## DarkSec API

```text
GET  https://darksec.uk/api/chat
GET  https://darksec.uk/api/chat?after=<last_id>
POST https://darksec.uk/api/chat
```

POST JSON:

```json
{"username":"PagerUser","message":"hello"}
```

Configure the username or an alternate compatible endpoint in `config.sh`.

## Runtime design

The Python application owns the LCD through `pagerctl`. Button presses are read
from pagerctl's queued input events, with state polling as a fallback. Pressing
A opens the keyboard inside the same LCD session, so composing a message does
not stop services, black the screen, or restart the chat application. The
native DuckyScript `TEXT_PICKER` is not used after takeover because current
firmware rejects it with code 1 once the custom LCD session has started.

Network sends run in the background, incoming website messages poll every
second, and the LCD redraws only when visible state changes.

## Logs

```text
/root/loot/darksec-chat/darksec_chat.log
/root/loot/darksec-chat/darksec_chat_app.log
```

The launcher log records Python exits and every keyboard handoff. The app log
records GET/POST failures and complete fatal tracebacks.
