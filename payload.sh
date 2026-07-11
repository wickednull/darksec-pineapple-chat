#!/bin/bash
# Title: DarkSec-Chat
# Description: Themed DarkSec web + mesh chat for WiFi Pineapple Pager
# Author: wickednull
# Version: 3.1
# Category: general
# Library: libpagerctl.so (pagerctl)

PAYLOAD_DIR="${_PAYLOAD_HOME:-}"
if [ -z "$PAYLOAD_DIR" ] || [ ! -f "$PAYLOAD_DIR/darksec_chat.py" ]; then
    for candidate in \
        /root/payloads/user/general/darksec-pineapple-chat \
        /root/payloads/user/general/darksec-chat \
        /mmc/root/payloads/user/general/darksec-pineapple-chat \
        /mmc/root/payloads/user/general/darksec-chat; do
        [ -f "$candidate/darksec_chat.py" ] && { PAYLOAD_DIR="$candidate"; break; }
    done
fi
[ -f "$PAYLOAD_DIR/darksec_chat.py" ] || { LOG red "DarkSec app not found"; exit 1; }

DATA_DIR="$PAYLOAD_DIR/data"
LOG_DIR="/root/loot/darksec-chat"
LOG_FILE="$LOG_DIR/darksec_chat.log"
RUNTIME_LIB_DIR="/tmp/darksec-chat-lib"
mkdir -p "$DATA_DIR" "$LOG_DIR" "$RUNTIME_LIB_DIR"

PAGERCTL_PY=""
PAGERCTL_SO=""
for dir in "$PAYLOAD_DIR/lib" "$PAYLOAD_DIR" \
    /root/payloads/user/utilities/PAGERCTL \
    /mmc/root/payloads/user/utilities/PAGERCTL /usr/lib /mmc/usr/lib; do
    [ -z "$PAGERCTL_PY" ] && [ -f "$dir/pagerctl.py" ] && PAGERCTL_PY="$dir/pagerctl.py"
    [ -z "$PAGERCTL_SO" ] && [ -f "$dir/libpagerctl.so" ] && PAGERCTL_SO="$dir/libpagerctl.so"
done

if [ -z "$PAGERCTL_PY" ] || [ -z "$PAGERCTL_SO" ]; then
    LOG red "pagerctl.py or libpagerctl.so is missing"
    LOG "Install PAGERCTL or copy both files into $PAYLOAD_DIR/lib"
    WAIT_FOR_INPUT >/dev/null 2>&1
    exit 1
fi

cp "$PAGERCTL_PY" "$RUNTIME_LIB_DIR/pagerctl.py" || exit 1
cp "$PAGERCTL_SO" "$RUNTIME_LIB_DIR/libpagerctl.so" || exit 1

export PATH="/mmc/usr/bin:$PATH"
export PYTHONPATH="$RUNTIME_LIB_DIR:$PAYLOAD_DIR:$PYTHONPATH"
export LD_LIBRARY_PATH="$RUNTIME_LIB_DIR:/mmc/usr/lib:/mmc/lib:$LD_LIBRARY_PATH"
[ -f "$PAYLOAD_DIR/config.sh" ] && . "$PAYLOAD_DIR/config.sh"
export WEB_API_URL USERNAME UDP_PORT TCP_PORT

PYTHON="$(command -v python3)"
if [ -z "$PYTHON" ] || ! "$PYTHON" -c "import ctypes" 2>/dev/null; then
    LOG red "Python 3 and python3-ctypes are required"
    WAIT_FOR_INPUT >/dev/null 2>&1
    exit 1
fi

cleanup() {
    /etc/init.d/pineapplepager start >/dev/null 2>&1
}
trap cleanup EXIT

LOG green "DarkSec-Chat 3.1"
LOG white "A = start"
LOG white "B = exit"
while true; do
    BUTTON="$(WAIT_FOR_INPUT)"
    case "$BUTTON" in
        A|GREEN) break ;;
        B|RED) exit 0 ;;
    esac
done

{
    echo "=== launch $(date) ==="
    echo "PAYLOAD_DIR=$PAYLOAD_DIR"
    echo "PAGERCTL_PY=$PAGERCTL_PY"
    echo "PAGERCTL_SO=$PAGERCTL_SO"
    echo "PYTHON=$PYTHON"
} > "$LOG_FILE"

SPINNER_ID="$(START_SPINNER "Starting DarkSec-Chat...")"
/etc/init.d/pineapplepager stop 2>/dev/null
sleep 0.5
STOP_SPINNER "$SPINNER_ID" 2>/dev/null

INPUT_REQUEST_FILE="$DATA_DIR/input_request"
PENDING_MESSAGE_FILE="$DATA_DIR/pending_message.txt"

while true; do
    echo "step=before_python_launch time=$(date)" >> "$LOG_FILE"
    "$PYTHON" -u "$PAYLOAD_DIR/darksec_chat.py" "$RUNTIME_LIB_DIR" >> "$LOG_FILE" 2>&1
    EXIT_CODE=$?
    echo "step=python_exit code=$EXIT_CODE time=$(date)" >> "$LOG_FILE"

    [ "$EXIT_CODE" -eq 43 ] || break

    REQUEST_KIND="$(cat "$INPUT_REQUEST_FILE" 2>/dev/null)"
    rm -f "$INPUT_REQUEST_FILE"
    # Exit 43 is reserved exclusively for message entry. Do not skip the
    # keyboard if the request breadcrumb was lost across the /tmp launcher or
    # an installed-path mismatch.
    [ "$REQUEST_KIND" = "message" ] || REQUEST_KIND="message"
    echo "step=keyboard_request kind=$REQUEST_KIND" >> "$LOG_FILE"

    # The Python UI has released pagerctl. Restore the native Pager UI and
    # invoke TEXT_PICKER from this original payload shell, exactly like Hak5's
    # supported examples.
    /etc/init.d/pineapplepager start 2>/dev/null
    sleep 2

    if [ "$REQUEST_KIND" = "message" ]; then
        USER_TEXT="$(TEXT_PICKER "DarkSec message" "")"
        PICKER_CODE=$?
        echo "step=text_picker_done code=$PICKER_CODE length=${#USER_TEXT}" >> "$LOG_FILE"
        case "$PICKER_CODE" in
            "$DUCKYSCRIPT_CANCELLED")
                echo "step=text_picker_cancelled" >> "$LOG_FILE"
                ;;
            "$DUCKYSCRIPT_REJECTED"|"$DUCKYSCRIPT_ERROR")
                echo "step=text_picker_error code=$PICKER_CODE" >> "$LOG_FILE"
                ERROR_DIALOG "DarkSec keyboard failed (code $PICKER_CODE)"
                ;;
            *) [ -n "$USER_TEXT" ] && printf '%s' "$USER_TEXT" > "$PENDING_MESSAGE_FILE" ;;
        esac
    fi

    SPINNER_ID="$(START_SPINNER "Returning to DarkSec...")"
    /etc/init.d/pineapplepager stop 2>/dev/null
    sleep 0.5
    STOP_SPINNER "$SPINNER_ID" 2>/dev/null
done

[ "$EXIT_CODE" -eq 0 ] || LOG red "DarkSec exited: $EXIT_CODE"
exit 0
