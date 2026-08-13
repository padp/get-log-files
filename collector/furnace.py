"""
Direct PLC polling for the log furnace controller -- a second, independent
signal for whether a log has moved from the table into the furnace queue,
separate from (and a possible cross-check against) the camera-based count
in log_count.py.

Unlike press.py (which reads press state that's already been written to
Mongo by a separate system), this connects straight to the furnace PLC over
EtherNet/IP via pylogix, through a multi-hop route (local backplane -> a
bridge module -> a remote rack on a different subnet).

Credentials/route live in ../secret/furnace.txt (KEY=VALUE per line: ip,
route as a Python literal list of (port, address) tuples), same pattern as
the camera/Plex secrets -- never hardcode PLC network details into a
tracked source file, since this repo is pushed to a public GitHub Pages
site.

Tags confirmed reachable and meaningful (2026-08-13): LOG_FILE[0]-[4] read
as real log lengths in inches (~240 = a full log, 0.0 = empty slot), and
SUM_OF_ALL_LOG_LENGTHS as its own PLC-computed tag. Not wired into the
collector loop yet -- still need the load-event detection logic (watch
LOG_FILE[2:] for a 0-to-nonzero transition, cross-checked against the sum
increasing) built on top of this before it's used for anything.

Usage: python furnace.py
"""
import ast
from pylogix import PLC

_CREDENTIALS_PATH = "../secret/furnace.txt"

_LOG_FILE_TAGS = [f"LOG_FILE[{i}]" for i in range(5)]
_SUM_TAG = "SUM_OF_ALL_LOG_LENGTHS"


def _load_credentials():
    creds = {}

    with open(_CREDENTIALS_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, _, value = line.partition("=")
            creds[key.strip()] = value.strip()

    creds["route"] = ast.literal_eval(creds["route"])
    return creds


def read_furnace_state():
    """Reads LOG_FILE[0]-[4] and SUM_OF_ALL_LOG_LENGTHS from the furnace PLC
    in one round trip. Returns {tag_name: value} on success. Raises on
    connection/read failure -- callers decide how to handle that, same as
    the rest of the collector (see camera.py's update_camera_snapshots for
    the self-contained-failure pattern this should eventually follow once
    wired into the main loop).

    Array semantics (per the user, 2026-08-13): the whole array shifts down
    as logs deplete -- index 0 is always the currently-depleting log, so a
    completed log doesn't leave a stale zero in place, everything above it
    shifts down to fill the gap. New logs load in at index 2 or higher, so
    a load-from-table event should show up as one of LOG_FILE[2:] going from
    0 to a real length. SUM_OF_ALL_LOG_LENGTHS only increases on an actual
    load (normal consumption only decreases individual slot values), so it's
    a useful redundant check against missing a load between polls."""
    creds = _load_credentials()

    with PLC() as comm:
        comm.IPAddress = creds["ip"]
        comm.Route = creds["route"]

        responses = comm.Read(_LOG_FILE_TAGS + [_SUM_TAG])

        values = {}
        for r in responses:
            if r.Status != "Success":
                raise RuntimeError(f"Failed reading {r.TagName}: {r.Status}")
            values[r.TagName] = r.Value

        return values


if __name__ == "__main__":
    try:
        values = read_furnace_state()
        for tag, value in values.items():
            print(f"{tag}: {value}")
    except Exception as e:
        print(f"[FURNACE] Failed to read tags: {e}")
