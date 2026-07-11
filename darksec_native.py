#!/usr/bin/env python3
"""Small dependency-free DarkSec API helper for the native Pager UI."""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def request(method, url, payload=None):
    body = None
    headers = {"Accept": "application/json", "User-Agent": "DarkSec-Pager/3.0"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=4) as response:
            raw = response.read().decode("utf-8", "replace")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raise RuntimeError("HTTP %s" % error.code) from error
    except urllib.error.URLError as error:
        raise RuntimeError("Connection: %s" % error.reason) from error


def load_last_id(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return int(json.load(handle).get("last_id", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 0


def save_last_id(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump({"last_id": value}, handle)
    os.replace(temp, path)


def poll(url, state_path):
    last_id = load_last_id(state_path)
    separator = "&" if "?" in url else "?"
    poll_url = url if last_id <= 0 else url + separator + urllib.parse.urlencode({"after": last_id})
    _, data = request("GET", poll_url)
    messages = data if isinstance(data, list) else (data or {}).get("messages", [])
    newest = last_id
    # On first launch, show only the latest screenful instead of flooding LOG.
    visible = messages[-8:] if last_id <= 0 else messages
    for message in messages:
        try:
            newest = max(newest, int(message.get("id", 0)))
        except (TypeError, ValueError):
            pass
    for message in visible:
        username = str(message.get("username", "Web")).replace("\n", " ")[:24]
        text = str(message.get("message", "")).replace("\r", " ").replace("\n", " ")[:220]
        if text:
            print("<%s> %s" % (username, text), flush=True)
    if newest > last_id:
        save_last_id(state_path, newest)


def send(url, username, message):
    status, _ = request("POST", url, {"username": username, "message": message})
    if not 200 <= status < 300:
        raise RuntimeError("HTTP %s" % status)


def main():
    try:
        if len(sys.argv) == 4 and sys.argv[1] == "poll":
            poll(sys.argv[2], sys.argv[3])
        elif len(sys.argv) == 5 and sys.argv[1] == "send":
            send(sys.argv[2], sys.argv[3], sys.argv[4])
        else:
            raise RuntimeError("invalid helper arguments")
    except Exception as error:
        print("ERROR: %s" % error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
