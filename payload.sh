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
DATA_DIR="$PAYLOAD_DIR/data"

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
PAGERCTL_SEARCH_DIRS="$PAYLOAD_DIR/lib $PAYLOAD_DIR /mmc/root/payloads/user/utilities/PAGERCTL /root/payloads/user/utilities/PAGERCTL /mmc/usr/lib /usr/lib"

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

# Copy to lib/ so pagerctl.py can load ./libpagerctl.so reliably.
mkdir -p "$PAYLOAD_DIR/lib" 2>/dev/null
if [ "$PAGERCTL_PY" != "$PAYLOAD_DIR/lib/pagerctl.py" ]; then
    cp "$PAGERCTL_PY" "$PAYLOAD_DIR/lib/pagerctl.py" 2>/dev/null
fi
if [ "$PAGERCTL_SO" != "$PAYLOAD_DIR/lib/libpagerctl.so" ]; then
    cp "$PAGERCTL_SO" "$PAYLOAD_DIR/lib/libpagerctl.so" 2>/dev/null
fi

#
# Setup local paths for bundled Python modules and native libs
#
export PATH="/mmc/usr/bin:$PATH"
export PYTHONPATH="$PAYLOAD_DIR/lib:$PAYLOAD_DIR:$PYTHONPATH"
export LD_LIBRARY_PATH="/mmc/usr/lib:$PAYLOAD_DIR/lib:$LD_LIBRARY_PATH"

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

# Check for requests (optional, enables web bridge)
if ! python3 -c "import requests" 2>/dev/null; then
    LOG "yellow" "python3-requests not found (web bridge disabled)"
    LOG "yellow" "Install: opkg -d mmc install python3-requests"
fi

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

# Create data directory
mkdir -p "$DATA_DIR" 2>/dev/null

# Stop pager service and take over display
SPINNER_ID=$(START_SPINNER "Starting DarkSec-Chat...")
/etc/init.d/pineapplepager stop 2>/dev/null
sleep 0.5
STOP_SPINNER "$SPINNER_ID" 2>/dev/null

# Payload loop -- supports exit code 42 handoff
NEXT_PAYLOAD_FILE="$DATA_DIR/.next_payload"

while true; do
    cd "$PAYLOAD_DIR"
    python3 darksec_chat.py
    EXIT_CODE=$?

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

exit 0
