"""
Grabs periodic snapshots from the "Log Pusher" Reolink camera channel and
prunes old ones after a retention period. This is feeding a prototype for
detecting physical load events at the log table (forktruck deliveries)
independent of any barcode scan -- for now it just builds a dated image
archive on disk to test counting approaches against.

Credentials live in ../secret/camera.txt (KEY=VALUE per line: ip,
username, password, channel), same pattern as the Plex/Mongo secrets --
never hardcode the camera password into a tracked source file, since this
repo is pushed to a public GitHub Pages site.
"""

import os
import time
import requests
from datetime import datetime, timedelta

SNAPSHOT_DIR = "camera_snapshots"
RETENTION_DAYS = 7

_CREDENTIALS_PATH = "../secret/camera.txt"

_token = None
_token_expires_at = None


def _load_credentials():
    creds = {}

    with open(_CREDENTIALS_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, _, value = line.partition("=")
            creds[key.strip()] = value.strip()

    return creds


def _login(creds):
    global _token, _token_expires_at

    base_url = f"http://{creds['ip']}/cgi-bin/api.cgi"
    payload = [{
        "cmd": "Login",
        "action": 0,
        "param": {"User": {"userName": creds["username"], "password": creds["password"]}},
    }]

    resp = requests.post(f"{base_url}?cmd=Login", json=payload, timeout=10)
    resp.raise_for_status()

    result = resp.json()[0]
    if result.get("code") != 0:
        raise RuntimeError(f"Camera login failed: {result}")

    _token = result["value"]["Token"]["name"]
    lease_seconds = result["value"]["Token"].get("leaseTime", 3600)

    # refresh a bit early rather than right at expiry
    _token_expires_at = datetime.utcnow() + timedelta(seconds=lease_seconds - 60)

    return _token


def _get_token(creds, force=False):
    if not force and _token and _token_expires_at and datetime.utcnow() < _token_expires_at:
        return _token

    return _login(creds)


def _snap(creds, token):
    base_url = f"http://{creds['ip']}/cgi-bin/api.cgi"
    channel = int(creds.get("channel", 0))

    return requests.get(
        base_url,
        params={"cmd": "Snap", "channel": channel, "token": token},
        timeout=10,
    )


def capture_snapshot():
    """Grabs one still from the configured channel and saves it to SNAPSHOT_DIR."""

    creds = _load_credentials()

    token = _get_token(creds)
    resp = _snap(creds, token)

    # the cached token can go stale server-side even before our tracked
    # expiry -- if the response isn't an image, force a fresh login and
    # retry once rather than failing the whole cycle over a stale token
    if not resp.headers.get("Content-Type", "").startswith("image/"):
        token = _get_token(creds, force=True)
        resp = _snap(creds, token)

    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if not content_type.startswith("image/"):
        raise RuntimeError(f"Expected an image, got Content-Type={content_type!r}: {resp.text[:300]}")

    os.makedirs(SNAPSHOT_DIR, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(SNAPSHOT_DIR, f"logpusher_{ts}.jpg")

    with open(path, "wb") as f:
        f.write(resp.content)

    return path


def prune_old_snapshots():
    """Deletes snapshots older than RETENTION_DAYS so they don't pile up on disk."""

    if not os.path.isdir(SNAPSHOT_DIR):
        return 0

    cutoff = time.time() - RETENTION_DAYS * 86400
    removed = 0

    for fname in os.listdir(SNAPSHOT_DIR):
        path = os.path.join(SNAPSHOT_DIR, fname)
        if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
            os.remove(path)
            removed += 1

    return removed


def update_camera_snapshots():
    """Capture-and-prune, self-contained: logs and swallows its own failures
    (camera offline, network hiccup, bad credentials) so a camera problem
    never takes down the rest of the collector loop."""

    try:
        path = capture_snapshot()
        print(f"[CAMERA] Saved {path}")
    except Exception as e:
        print(f"[CAMERA] Failed to capture snapshot: {e}")
        return

    try:
        removed = prune_old_snapshots()
        if removed:
            print(f"[CAMERA] Pruned {removed} snapshot(s) older than {RETENTION_DAYS} days")
    except Exception as e:
        print(f"[CAMERA] Failed to prune old snapshots: {e}")
