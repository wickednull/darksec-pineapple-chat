#!/bin/bash
# Title: DarkSec-Chat
# Description: Native Pager chat client for darksec.uk/chat
# Author: wickednull
# Version: 3.0
# Category: general

# Use only Hak5's native payload UI.  TEXT_PICKER and WAIT_FOR_INPUT are owned
# by pineapplepager, so this payload deliberately does not stop that service.

PAYLOAD_DIR="${_PAYLOAD_HOME:-$(cd "$(dirname "$0")" 2>/dev/null && pwd)}"
[ -f "$PAYLOAD_DIR/darksec_native.py" ] || {
    LOG red "DarkSec helper not found"
    exit 1
}

DATA_DIR="/root/loot/darksec-chat"
STATE_FILE="$DATA_DIR/native_state.json"
LOG_FILE="$DATA_DIR/darksec_chat.log"
POLL_FILE="/tmp/darksec-chat-poll.$$"
mkdir -p "$DATA_DIR"

WEB_API_URL="https://darksec.uk/api/chat"
USERNAME="PagerUser"
[ -f "$PAYLOAD_DIR/config.sh" ] && . "$PAYLOAD_DIR/config.sh"
[ -n "${WEB_API_URL:-}" ] || WEB_API_URL="https://darksec.uk/api/chat"
[ -n "${USERNAME:-}" ] || USERNAME="PagerUser"

PYTHON="$(command -v python3)"
if [ -z "$PYTHON" ]; then
    LOG red "Python 3 is required"
    LOG "Install python3 from Packages"
    WAIT_FOR_INPUT >/dev/null 2>&1
    exit 1
fi

cleanup() {
    [ -n "${POLL_PID:-}" ] && kill "$POLL_PID" 2>/dev/null
    rm -f "$POLL_FILE"
}
trap cleanup EXIT

write_log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"
}

start_poll() {
    : > "$POLL_FILE"
    POLL_DELAY="${1:-0}"
    (
        [ "$POLL_DELAY" = "0" ] || sleep "$POLL_DELAY"
        "$PYTHON" "$PAYLOAD_DIR/darksec_native.py" poll \
            "$WEB_API_URL" "$STATE_FILE" > "$POLL_FILE" 2>> "$LOG_FILE"
    ) &
    POLL_PID=$!
}

show_poll() {
    [ -s "$POLL_FILE" ] || return
    while IFS= read -r line; do
        case "$line" in
            ERROR:*)
                write_log "$line"
                ;;
            *)
                [ -n "$line" ] && LOG white "$line"
                ;;
        esac
    done < "$POLL_FILE"
}

LOG ""
LOG green "=== DARKSEC CHAT ==="
LOG white "Connected to darksec.uk/chat"
LOG white "A = write message"
LOG white "B = exit"
LOG ""
write_log "native chat started api=$WEB_API_URL user=$USERNAME"

start_poll
while true; do
    # A short timeout keeps buttons responsive while the HTTP poll runs in a
    # separate process.  The UI never waits on DNS, TLS, or the server.
    BUTTON="$(WAIT_FOR_INPUT 0.2)"

    if [ -n "${POLL_PID:-}" ] && ! kill -0 "$POLL_PID" 2>/dev/null; then
        wait "$POLL_PID" 2>/dev/null
        POLL_PID=""
        show_poll
        start_poll 1
    fi

    case "$BUTTON" in
        A|GREEN)
            MESSAGE="$(TEXT_PICKER "DarkSec message" "")"
            PICKER_CODE=$?
            case "$PICKER_CODE" in
                "$DUCKYSCRIPT_CANCELLED"|"$DUCKYSCRIPT_REJECTED"|"$DUCKYSCRIPT_ERROR")
                    write_log "text picker cancelled/rejected code=$PICKER_CODE"
                    continue
                    ;;
            esac
            [ -n "$MESSAGE" ] || continue

            SPINNER_ID="$(START_SPINNER "Sending to DarkSec...")"
            SEND_RESULT="$("$PYTHON" "$PAYLOAD_DIR/darksec_native.py" send \
                "$WEB_API_URL" "$USERNAME" "$MESSAGE" 2>> "$LOG_FILE")"
            SEND_CODE=$?
            STOP_SPINNER "$SPINNER_ID" 2>/dev/null
            if [ "$SEND_CODE" -eq 0 ]; then
                LOG green "You: $MESSAGE"
                write_log "message sent length=${#MESSAGE}"
            else
                LOG red "Send failed"
                [ -n "$SEND_RESULT" ] && LOG red "$SEND_RESULT"
                write_log "send failed code=$SEND_CODE result=$SEND_RESULT"
            fi
            ;;
        B|RED|POWER)
            LOG white "Leaving DarkSec Chat"
            exit 0
            ;;
    esac
done
