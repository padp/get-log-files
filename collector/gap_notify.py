"""
Pushes an ntfy.sh notification when the delivered-vs-moved gap
(api/reconciliation.py's get_gap_status) has stayed open long enough to
alert on. This is exactly the reuse api/reconciliation.py's module
docstring anticipated -- get_gap_status is Flask-free specifically so a
notifier could call it on its own cadence, independent of anyone having
the dashboard open. Runs from the collector's own already-continuous loop
rather than standing up a second always-on process or a paid Render cron
job -- free, and no new deployment step beyond the normal "sync updated
code to the collector PC" every other change here has needed.

Dedup persists in Mongo (a new, tiny single-doc notify_state collection),
not memory, so a collector restart doesn't re-notify for a gap incident it
already alerted on. Keyed by gapOpenSince, the same dedupe key
api/reconciliation.py's docstring called out for this.

Credentials in ../secret/ntfy.txt (KEY=VALUE, same pattern as
camera.txt/furnace.txt) -- topic=<your-ntfy-topic>. Silently does nothing
if that file doesn't exist yet (not configured), same as every other
optional integration in this collector.
"""
import os
import requests
from datetime import datetime

import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
from reconciliation import get_gap_status  # noqa: E402  (path must be set up first)

from database import inventory as lf_collection, table_events, db

_CREDENTIALS_PATH = "../secret/ntfy.txt"
_notify_state = db["notify_state"]


def _load_topic():
    try:
        with open(_CREDENTIALS_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith("topic="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        return None
    return None


def check_and_notify_gap():
    topic = _load_topic()
    if not topic:
        return

    status = get_gap_status(lf_collection, table_events)

    if not status["gapAlert"]:
        return

    gap_open_since = status["gapOpenSince"]

    state = _notify_state.find_one({"_id": "gap_alert"}) or {}
    if state.get("lastNotifiedGapOpenSince") == gap_open_since:
        return  # already notified for this exact incident, don't repeat every cycle

    message = (
        f"{round(status['gapOpenMinutes'])} min open, "
        f"net difference {status['netDifference']}. "
        f"Check physical tags at the table against recent deliveries."
    )

    try:
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            headers={"Title": "Log table delivery gap", "Priority": "high", "Tags": "warning"},
            timeout=10,
        )
    except requests.RequestException as e:
        print(f"[GAP-NOTIFY] Failed to send ntfy notification: {e}")
        return  # don't mark as notified if the send failed -- retry next cycle

    _notify_state.update_one(
        {"_id": "gap_alert"},
        {"$set": {"lastNotifiedGapOpenSince": gap_open_since, "notifiedAt": datetime.utcnow()}},
        upsert=True,
    )
    print(f"[GAP-NOTIFY] Sent gap alert notification (open since {gap_open_since})")
