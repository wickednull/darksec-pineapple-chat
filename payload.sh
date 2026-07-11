#!/bin/sh
# Title: DarkSec-Chat
# Description: Mesh networking + web bridge chat client with LCD UI
# Author: wickednull
# Version: 2.0
# Category: general
# Library: libpagerctl.so (pagerctl)

# Payload metadata for pager theme engine
_PAYLOAD_TITLE="DarkSec-Chat"
_PAYLOAD_AUTHOR_NAME="wickednull"
_PAYLOAD_VERSION="2.0"
_PAYLOAD_DESCRIPTION="Mesh + Web Chat Client for WiFi Pineapple Pager"

# Hak5 runs payloads from /tmp and exposes the real install directory through
# _PAYLOAD_HOME. Prefer that documented path; retain fallbacks for older
# firmware and manual SSH launches where the variable may not be present.
if [ -n "${_PAYLOAD_HOME:-}" ] && [ -f "${_PAYLOAD_HOME}/darksec_chat.py" ]; then
    PAYLOAD_DIR="${_PAYLOAD_HOME}"
else
    SCRIPT_PATH="$0"
    case "$SCRIPT_PATH" in
        /*) ;;
        *) SCRIPT_PATH="$(pwd)/$SCRIPT_PATH" ;;
    esac

    PAYLOAD_DIR="$(dirname "$SCRIPT_PATH")"
    PAYLOAD_DIR="$(cd "$PAYLOAD_DIR" 2>/dev/null && pwd)"
    if [ -z "$PAYLOAD_DIR" ]; then
        PAYLOAD_DIR="$(pwd)"
    fi
fi

if [ ! -f "$PAYLOAD_DIR/darksec_chat.py" ]; then
    for candidate in \
        /root/payloads/user/general/darksec-chat \
        /root/payloads/user/general/darksec-pineapple-chat \
        /mmc/root/payloads/user/general/darksec-chat \
        /mmc/root/payloads/user/general/darksec-pineapple-chat; do
        if [ -f "$candidate/darksec_chat.py" ] && [ -f "$candidate/payload.sh" ]; then
            PAYLOAD_DIR="$candidate"
            break
        fi
    done
fi

if [ ! -f "$PAYLOAD_DIR/darksec_chat.py" ]; then
    FOUND_PAYLOAD="$(find /root/payloads /mmc/root/payloads -path '*/darksec_chat.py' 2>/dev/null | head -n 1)"
    if [ -n "$FOUND_PAYLOAD" ]; then
        PAYLOAD_DIR="$(dirname "$FOUND_PAYLOAD")"
    fi
fi

DATA_DIR="$PAYLOAD_DIR/data"
LOG_DIR="/root/loot/darksec-chat"
LOG_FILE="$LOG_DIR/darksec_chat.log"

cd "$PAYLOAD_DIR" || {
    LOG "red" "ERROR: $PAYLOAD_DIR not found"
    exit 1
}

#
# Find and setup pagerctl dependencies.
# pagerctl.py and libpagerctl.so may come from different locations, so find
# them independently and stage both into lib/ for Python's ctypes loader.
#
PAGERCTL_PY=""
PAGERCTL_SO=""
RUNTIME_LIB_DIR="/tmp/darksec-chat-lib"
PAGERCTL_SEARCH_DIRS="$PAYLOAD_DIR/lib $PAYLOAD_DIR /tmp/lib /mmc/root/payloads/user/utilities/PAGERCTL /root/payloads/user/utilities/PAGERCTL /mmc/usr/lib /usr/lib"

for dir in $PAGERCTL_SEARCH_DIRS; do
    if [ -z "$PAGERCTL_PY" ] && [ -f "$dir/pagerctl.py" ]; then
        PAGERCTL_PY="$dir/pagerctl.py"
    fi
    if [ -z "$PAGERCTL_SO" ] && [ -f "$dir/libpagerctl.so" ]; then
        PAGERCTL_SO="$dir/libpagerctl.so"
    fi
done

if [ -z "$PAGERCTL_PY" ] || [ -z "$PAGERCTL_SO" ]; then
    LOG ""
    LOG "red" "=== MISSING DEPENDENCY ==="
    LOG ""
    [ -z "$PAGERCTL_PY" ] && LOG "red" "pagerctl.py not found!"
    [ -z "$PAGERCTL_SO" ] && LOG "red" "libpagerctl.so not found!"
    LOG ""
    LOG "Searched:"
    for dir in $PAGERCTL_SEARCH_DIRS; do
        LOG "  $dir"
    done
    LOG ""
    LOG "Install PAGERCTL or copy missing files to:"
    LOG "  $PAYLOAD_DIR/lib/"
    LOG ""
    LOG "Press any button to exit..."
    WAIT_FOR_INPUT >/dev/null 2>&1
    exit 1
fi

# Stage both files together in writable runtime storage so pagerctl.py can load
# ./libpagerctl.so reliably even when Hak5 launches the payload from /tmp.
rm -rf "$RUNTIME_LIB_DIR" 2>/dev/null
mkdir -p "$RUNTIME_LIB_DIR" 2>/dev/null
cp "$PAGERCTL_PY" "$RUNTIME_LIB_DIR/pagerctl.py" 2>/dev/null
cp "$PAGERCTL_SO" "$RUNTIME_LIB_DIR/libpagerctl.so" 2>/dev/null

if [ ! -f "$RUNTIME_LIB_DIR/pagerctl.py" ] || [ ! -f "$RUNTIME_LIB_DIR/libpagerctl.so" ]; then
    LOG "red" "Failed to stage pagerctl runtime files."
    LOG "red" "Source py: $PAGERCTL_PY"
    LOG "red" "Source so: $PAGERCTL_SO"
    LOG "red" "Target: $RUNTIME_LIB_DIR"
    WAIT_FOR_INPUT >/dev/null 2>&1
    exit 1
fi

#
# Setup local paths for bundled Python modules and native libs
#
export PATH="/mmc/usr/bin:$PATH"
export PYTHONPATH="$RUNTIME_LIB_DIR:$PAYLOAD_DIR:$PYTHONPATH"
export LD_LIBRARY_PATH="$RUNTIME_LIB_DIR:/mmc/usr/lib:/mmc/lib:$LD_LIBRARY_PATH"

# Source config
if [ -f "$PAYLOAD_DIR/config.sh" ]; then
    . "$PAYLOAD_DIR/config.sh"
    export WEB_API_URL USERNAME UDP_PORT TCP_PORT
fi

#
# Check for Python3 and python3-ctypes - required system dependencies
#
NEED_PYTHON=false
NEED_CTYPES=false

if ! command -v python3 >/dev/null 2>&1; then
    NEED_PYTHON=true
    NEED_CTYPES=true
elif ! python3 -c "import ctypes" 2>/dev/null; then
    NEED_CTYPES=true
fi

if [ "$NEED_PYTHON" = true ] || [ "$NEED_CTYPES" = true ]; then
    LOG ""
    LOG "red" "=== MISSING REQUIREMENT ==="
    LOG ""
    if [ "$NEED_PYTHON" = true ]; then
        LOG "Python3 is required to run DarkSec-Chat."
    else
        LOG "Python3-ctypes is required to run DarkSec-Chat."
    fi
    LOG ""
    LOG "green" "GREEN = Install dependencies (requires internet)"
    LOG "red" "RED   = Exit"
    LOG ""

    while true; do
        BUTTON=$(WAIT_FOR_INPUT 2>/dev/null)
        case "$BUTTON" in
            "GREEN"|"A")
                LOG ""
                LOG "Updating package lists..."
                opkg update 2>&1 | while IFS= read -r line; do LOG "  $line"; done
                LOG ""
                LOG "Installing Python3 + ctypes to MMC..."
                opkg -d mmc install python3 python3-ctypes 2>&1 | while IFS= read -r line; do LOG "  $line"; done
                LOG ""
                if command -v python3 >/dev/null 2>&1 && python3 -c "import ctypes" 2>/dev/null; then
                    LOG "green" "Python3 installed successfully!"
                    sleep 1
                else
                    LOG "red" "Failed to install Python3"
                    LOG "red" "Check internet connection and try again."
                    LOG ""
                    LOG "Press any button to exit..."
                    WAIT_FOR_INPUT >/dev/null 2>&1
                    exit 1
                fi
                break
                ;;
            "RED"|"B")
                LOG "Exiting."
                exit 0
                ;;
        esac
    done
fi

PYTHON=$(command -v python3)

# ============================================================
# CLEANUP
# ============================================================

cleanup() {
    # Restart pager service if not running
    if ! pgrep -x pineapple >/dev/null 2>&1; then
        /etc/init.d/pineapplepager start 2>/dev/null
    fi
}

trap cleanup EXIT

# ============================================================
# MAIN
# ============================================================

LOG ""
LOG "green" "================================"
LOG "green" "       DarkSec-Chat v2"
LOG "green" "  Mesh + Web Chat for Pager"
LOG "green" "================================"
LOG ""
LOG "Launching chat client..."
LOG ""
LOG "green" "  GREEN = Start DarkSec-Chat"
LOG "red" "  RED   = Exit"
LOG ""

while true; do
    BUTTON=$(WAIT_FOR_INPUT 2>/dev/null)
    case "$BUTTON" in
        "GREEN"|"A")
            break
            ;;
        "RED"|"B")
            LOG "Exiting."
            exit 0
            ;;
    esac
done

# Create data and log directories before any service changes.
mkdir -p "$DATA_DIR" 2>/dev/null
mkdir -p "$LOG_DIR" 2>/dev/null

{
    echo "=== DarkSec-Chat launch $(date) ==="
    echo "step=after_green_button"
    echo "PAYLOAD_DIR=$PAYLOAD_DIR"
    echo "PAGERCTL_PY=$PAGERCTL_PY"
    echo "PAGERCTL_SO=$PAGERCTL_SO"
    echo "RUNTIME_LIB_DIR=$RUNTIME_LIB_DIR"
    ls -l "$RUNTIME_LIB_DIR"
    echo "PYTHON=$PYTHON"
    sync
} > "$LOG_FILE" 2>&1

# Stop only the Pager UI service and take over display.
SPINNER_ID=$(START_SPINNER "Starting DarkSec-Chat...")
{
    echo "step=before_pineapplepager_stop"
    sync
} >> "$LOG_FILE" 2>&1
/etc/init.d/pineapplepager stop 2>/dev/null
sleep 0.5
STOP_SPINNER "$SPINNER_ID" 2>/dev/null

# Payload loop -- supports exit code 42 handoff
NEXT_PAYLOAD_FILE="$DATA_DIR/.next_payload"
INPUT_REQUEST_FILE="$DATA_DIR/input_request"
PENDING_MESSAGE_FILE="$DATA_DIR/pending_message.txt"

while true; do
    cd "$PAYLOAD_DIR"
    {
        echo "step=before_python_launch"
        sync
    } >> "$LOG_FILE" 2>&1
    "$PYTHON" -u "$PAYLOAD_DIR/darksec_chat.py" "$RUNTIME_LIB_DIR" >> "$LOG_FILE" 2>&1
    EXIT_CODE=$?

    if [ "$EXIT_CODE" -eq 43 ]; then
        {
            echo "step=input_request_exit"
            cat "$INPUT_REQUEST_FILE" 2>/dev/null
            sync
        } >> "$LOG_FILE" 2>&1

        /etc/init.d/pineapplepager start 2>/dev/null
        sleep 0.5

        REQUEST_KIND="$(cat "$INPUT_REQUEST_FILE" 2>/dev/null)"
        rm -f "$INPUT_REQUEST_FILE"

        if [ "$REQUEST_KIND" = "message" ]; then
            USER_TEXT=$(TEXT_PICKER "DarkSec message" "")
            PICKER_CODE=$?
            {
                echo "step=text_picker_done code=$PICKER_CODE length=${#USER_TEXT}"
                sync
            } >> "$LOG_FILE" 2>&1
            if [ "$PICKER_CODE" -eq 0 ] && [ -n "$USER_TEXT" ]; then
                printf "%s" "$USER_TEXT" > "$PENDING_MESSAGE_FILE"
            fi
        fi

        SPINNER_ID=$(START_SPINNER "Returning to DarkSec...")
        /etc/init.d/pineapplepager stop 2>/dev/null
        sleep 0.5
        STOP_SPINNER "$SPINNER_ID" 2>/dev/null
        continue
    fi

    # Exit code 42 = hand off to another payload
    if [ "$EXIT_CODE" -eq 42 ] && [ -f "$NEXT_PAYLOAD_FILE" ]; then
        NEXT_SCRIPT=$(cat "$NEXT_PAYLOAD_FILE")
        rm -f "$NEXT_PAYLOAD_FILE"
        if [ -f "$NEXT_SCRIPT" ]; then
            sh "$NEXT_SCRIPT"
            [ $? -eq 42 ] && continue
        fi
    fi

    break
done

if [ "$EXIT_CODE" -ne 0 ]; then
    LOG "DarkSec-Chat exited with code $EXIT_CODE"
    LOG "Check $LOG_FILE for details"
fi

sleep 0.5

/etc/init.d/pineapplepager start 2>/dev/null &

exit 0
